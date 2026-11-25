"""管理后台审计动作、对象类型和状态的中文展示映射。"""

from __future__ import annotations

AUDIT_ACTION_LABELS = {
    "COMPANY_LICENSE_UPLOAD": "上传公司营业执照",
    "COMPANY_PROFILE_CREATE": "创建公司资料",
    "COMPANY_PROFILE_UPDATE": "更新公司资料",
    "USER_BAN": "封禁用户",
    "USER_UNBAN": "解封用户",
    "USER_BALANCE_CLEAR": "清空用户余额",
    "USER_FORCE_DELETE": "强制注销用户",
    "ORDER_CANCEL": "取消订单",
    "WITHDRAWAL_APPROVE": "审核通过提现",
    "WITHDRAWAL_REJECT": "拒绝提现",
    "WITHDRAWAL_RETRY": "重新发起提现",
    "PROVIDER_SUSPEND": "停用服务者",
    "PROVIDER_RESTORE": "恢复服务者",
    "ADMIN_ROLE_CREATE": "创建管理角色",
    "ADMIN_ROLE_UPDATE": "更新管理角色",
    "ADMIN_ROLE_DELETE": "删除管理角色",
    "ADMIN_ROLE_MEMBER_ADD": "添加角色成员",
    "ADMIN_ROLE_MEMBER_REMOVE": "移除角色成员",
    "SYSTEM_SETTING_UPDATE": "更新系统设置",
    "ANNOUNCEMENT_CREATE": "创建平台公告",
    "ANNOUNCEMENT_UPDATE": "更新平台公告",
    "CITY_CREATE": "创建城市配置",
    "CITY_UPDATE": "更新城市配置",
    "SERVICE_CATEGORY_CREATE": "创建服务类目",
    "SERVICE_CATEGORY_UPDATE": "更新服务类目",
    "SUPPORT_TICKET_ASSIGN": "分配客服工单",
    "SUPPORT_TICKET_RESOLVE": "解决客服工单",
    "SUPPORT_TICKET_CLOSE": "关闭客服工单",
    "SUPPORT_FAQ_CREATE": "创建客服常见问题",
    "SUPPORT_FAQ_UPDATE": "更新客服常见问题",
    "REPORT_RESOLVE": "处理内容举报",
    "REPORT_REJECT": "驳回内容举报",
    "SENSITIVE_WORD_CREATE": "创建敏感词",
    "SENSITIVE_WORD_UPDATE": "更新敏感词",
    "SENSITIVE_WORD_DELETE": "删除敏感词",
}

AUDIT_TARGET_TYPE_LABELS = {
    "COMPANY_LICENSE": "公司营业执照",
    "COMPANY_PROFILE": "公司资料",
    "USER": "用户",
    "ORDER": "订单",
    "WITHDRAWAL": "提现申请",
    "PROVIDER": "服务者",
    "ADMIN_ROLE": "管理角色",
    "ADMIN_ROLE_MEMBER": "管理角色成员",
    "SYSTEM_SETTING": "系统设置",
    "ANNOUNCEMENT": "平台公告",
    "CITY": "城市配置",
    "SERVICE_CATEGORY": "服务类目",
    "SUPPORT_TICKET": "客服工单",
    "SUPPORT_FAQ": "客服常见问题",
    "CONTENT_REPORT": "内容举报",
    "SENSITIVE_WORD": "敏感词",
}


def audit_action_label(action: str) -> str:
    """返回管理审计动作中文名称，未知动作保留可见的未知标记。"""
    return AUDIT_ACTION_LABELS.get(action, "未知操作")


def audit_target_type_label(target_type: str) -> str:
    """返回管理审计对象类型中文名称。"""
    return AUDIT_TARGET_TYPE_LABELS.get(target_type, "未知对象")
