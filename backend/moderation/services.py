"""内容举报提交、处理和敏感词配置业务服务。"""

from __future__ import annotations

from typing import Any

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from backend.accounts.models import User
from backend.adminops.auth import write_admin_operation
from backend.common.display import enum_label
from backend.common.errors import ERROR_MESSAGES, ErrorCode
from backend.common.exceptions import ApiError
from backend.moderation.models import ContentReport, SensitiveWord


def _invalid(field: str, message: str) -> ApiError:
    return ApiError(
        ErrorCode.VALIDATION_ERROR,
        message,
        status_code=400,
        details={field: message},
    )


def report_payload(report: ContentReport) -> dict[str, Any]:
    """返回举报安全摘要。"""
    return {
        "report_no": str(report.report_no),
        "reporter_public_id": str(report.reporter.public_id),
        "target_type": report.target_type,
        "target_type_text": enum_label(
            ContentReport.TargetType,
            report.target_type,
        ),
        "target_id": report.target_id,
        "reason": report.reason,
        "evidence_urls": report.evidence_urls,
        "status": report.status,
        "status_text": enum_label(ContentReport.Status, report.status),
        "resolution": report.resolution,
        "handled_at": report.handled_at,
        "version": report.version,
        "created_at": report.created_at,
        "updated_at": report.updated_at,
    }


def create_content_report(
    *,
    user: User,
    payload: dict[str, Any],
    idempotency_key: str = "",
) -> ContentReport:
    """用户提交内容举报，同一用户同一目标重复举报幂等。"""
    target_type = str(payload.get("target_type", "")).upper()
    target_id = str(payload.get("target_id", "")).strip()
    reason = str(payload.get("reason", "")).strip()
    evidence_urls = payload.get("evidence_urls") or []
    if target_type not in ContentReport.TargetType.values:
        raise _invalid("target_type", "举报对象类型不存在")
    if not target_id or len(target_id) > 128:
        raise _invalid("target_id", "举报对象标识不正确")
    if not 2 <= len(reason) <= 500:
        raise _invalid("reason", "举报原因长度必须为 2 到 500 个字符")
    if not isinstance(evidence_urls, list) or len(evidence_urls) > 9:
        raise _invalid("evidence_urls", "证据地址必须是最多 9 项的列表")
    return ContentReport.objects.create(
        reporter=user,
        target_type=target_type,
        target_id=target_id,
        reason=reason,
        evidence_urls=evidence_urls,
    )


def list_content_reports(
    *,
    status: str = "",
    target_type: str = "",
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    """分页查询举报。"""
    queryset = ContentReport.objects.select_related("reporter")
    if status:
        queryset = queryset.filter(status=status)
    if target_type:
        queryset = queryset.filter(target_type=target_type)
    total = queryset.count()
    items = queryset.order_by("-created_at", "-id")[(page - 1) * page_size : page * page_size]
    return {
        "items": [report_payload(item) for item in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def resolve_content_report(
    *,
    operator: User,
    report_no: str,
    action: str,
    expected_version: int,
    resolution: str,
) -> dict[str, Any]:
    """处理或驳回举报并写审计。"""
    if action not in {"resolve", "reject"}:
        raise _invalid("action", "举报处理动作不存在")
    if len(resolution.strip()) < 2:
        raise _invalid("resolution", "处理结论至少需要 2 个字符")
    with transaction.atomic():
        report = ContentReport.objects.select_for_update().filter(report_no=report_no).first()
        if report is None:
            raise ApiError(
                ErrorCode.NOT_FOUND,
                ERROR_MESSAGES[ErrorCode.NOT_FOUND],
                status_code=404,
            )
        if report.status != ContentReport.Status.PENDING:
            raise _invalid("status", "举报已经处理")
        if report.version != expected_version:
            raise ApiError(
                ErrorCode.ADMIN_VERSION_CONFLICT,
                ERROR_MESSAGES[ErrorCode.ADMIN_VERSION_CONFLICT],
                status_code=409,
            )
        before = report_payload(report)
        report.status = (
            ContentReport.Status.RESOLVED if action == "resolve" else ContentReport.Status.REJECTED
        )
        report.resolution = resolution
        report.handled_by = operator.id
        report.handled_at = timezone.now()
        report.version = F("version") + 1
        report.save()
        report.refresh_from_db()
        write_admin_operation(
            operator=operator,
            action=f"REPORT_{action.upper()}",
            target_type="CONTENT_REPORT",
            target_id=report_no,
            before_state=before,
            after_state=report_payload(report),
            reason=resolution,
        )
        return report_payload(report)


def sensitive_word_payload(word: SensitiveWord) -> dict[str, Any]:
    """返回敏感词安全摘要。"""
    return {
        "word_id": word.id,
        "word": word.word,
        "category": word.category,
        "action": word.action,
        "action_text": enum_label(SensitiveWord.Action, word.action),
        "status": word.status,
        "status_text": enum_label(SensitiveWord.Status, word.status),
        "version": word.version,
        "created_at": word.created_at,
        "updated_at": word.updated_at,
    }


def list_sensitive_words(*, status: str = "", page: int = 1, page_size: int = 20) -> dict[str, Any]:
    """分页查询敏感词。"""
    queryset = SensitiveWord.objects.all()
    if status:
        queryset = queryset.filter(status=status)
    total = queryset.count()
    items = queryset.order_by("word")[(page - 1) * page_size : page * page_size]
    return {
        "items": [sensitive_word_payload(item) for item in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def create_sensitive_word(*, operator: User, payload: dict[str, Any]) -> dict[str, Any]:
    """创建敏感词配置。"""
    word = str(payload.get("word", "")).strip()
    if not word or len(word) > 100:
        raise _invalid("word", "敏感词长度必须为 1 到 100 个字符")
    try:
        item = SensitiveWord.objects.create(
            word=word,
            category=str(payload.get("category", "DEFAULT")).strip() or "DEFAULT",
            action=payload.get("action", SensitiveWord.Action.REVIEW),
            status=payload.get("status", SensitiveWord.Status.ACTIVE),
        )
    except Exception as exc:
        raise ApiError(
            ErrorCode.ADMIN_VERSION_CONFLICT,
            "敏感词已存在",
            status_code=409,
        ) from exc
    write_admin_operation(
        operator=operator,
        action="SENSITIVE_WORD_CREATE",
        target_type="SENSITIVE_WORD",
        target_id=str(item.id),
        after_state=sensitive_word_payload(item),
    )
    return sensitive_word_payload(item)


def update_sensitive_word(
    *,
    operator: User,
    word_id: int,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """修改敏感词状态或处理动作。"""
    with transaction.atomic():
        item = SensitiveWord.objects.select_for_update().filter(id=word_id).first()
        if item is None:
            raise ApiError(
                ErrorCode.NOT_FOUND,
                ERROR_MESSAGES[ErrorCode.NOT_FOUND],
                status_code=404,
            )
        if item.version != payload["expected_version"]:
            raise ApiError(
                ErrorCode.ADMIN_VERSION_CONFLICT,
                ERROR_MESSAGES[ErrorCode.ADMIN_VERSION_CONFLICT],
                status_code=409,
            )
        before = sensitive_word_payload(item)
        for field in ("category", "action", "status"):
            if field in payload:
                setattr(item, field, payload[field])
        item.version = F("version") + 1
        item.save()
        item.refresh_from_db()
        write_admin_operation(
            operator=operator,
            action="SENSITIVE_WORD_UPDATE",
            target_type="SENSITIVE_WORD",
            target_id=str(word_id),
            before_state=before,
            after_state=sensitive_word_payload(item),
        )
        return sensitive_word_payload(item)


def delete_sensitive_word(
    *, operator: User, word_id: int, expected_version: int
) -> dict[str, bool]:
    """停用并逻辑删除敏感词配置。"""
    with transaction.atomic():
        item = SensitiveWord.objects.select_for_update().filter(id=word_id).first()
        if item is None:
            raise ApiError(
                ErrorCode.NOT_FOUND,
                ERROR_MESSAGES[ErrorCode.NOT_FOUND],
                status_code=404,
            )
        if item.version != expected_version:
            raise ApiError(
                ErrorCode.ADMIN_VERSION_CONFLICT,
                ERROR_MESSAGES[ErrorCode.ADMIN_VERSION_CONFLICT],
                status_code=409,
            )
        before = sensitive_word_payload(item)
        item.status = SensitiveWord.Status.DISABLED
        item.version = F("version") + 1
        item.save()
        item.refresh_from_db()
        write_admin_operation(
            operator=operator,
            action="SENSITIVE_WORD_DELETE",
            target_type="SENSITIVE_WORD",
            target_id=str(word_id),
            before_state=before,
            after_state=sensitive_word_payload(item),
        )
        return {"deleted": True}
