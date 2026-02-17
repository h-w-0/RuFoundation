from django.contrib.admin.views.decorators import staff_member_required
from django.utils.decorators import method_decorator
from django.shortcuts import redirect, resolve_url
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.contrib.admin.models import LogEntry, CHANGE
from django.views.generic import FormView
from django.contrib.admin import site
from django.contrib import messages
from django.forms import Form

from web.models.articles import Vote


User = get_user_model()


@method_decorator(staff_member_required, name='dispatch')
class ResetUserVotesView(FormView):
    """管理员重置用户投票视图（仅后台工作人员可访问）"""
    form_class = Form
    template_name = 'admin/web/user/user_action.html'

    def get_initial(self):
        """获取表单初始数据（此处无自定义初始值）"""
        initial = super(ResetUserVotesView, self).get_initial()
        return initial
    
    def get_user(self) -> User | None:
        """根据URL中的ID参数获取目标用户对象"""
        user_id = self.kwargs.get('id') or None
        if user_id:
            return User.objects.get(pk=user_id)
        return None

    def get_context_data(self, **kwargs):
        """构建页面上下文，设置后台操作页面的文本和样式"""
        context = super(ResetUserVotesView, self).get_context_data(** kwargs)
        # 页面标题、提示文本、按钮文案汉化
        context['title'] = '重置用户投票'
        context['after_text'] = ('您确定要重置该用户的所有评分吗？'
                                 '此操作不可撤销。')
        context['after_text_style'] = 'color: red'  # 提示文本红色高亮
        context['is_danger'] = True  # 标记为危险操作
        context['submit_btn'] = '确认重置'
        # 补充admin站点的通用上下文（如菜单、权限等）
        context.update(site.each_context(self.request))
        return context

    def get_success_url(self):
        """操作成功后的跳转地址（返回admin首页）"""
        return resolve_url('admin:index')

    def form_valid(self, form):
        """处理表单提交的核心逻辑：删除用户所有投票并记录操作日志"""
        user = self.get_user()
        if not user:
            messages.error(self.request, "用户不存在")
        else:
            # 删除该用户的所有投票记录
            Vote.objects.filter(user=user).delete()

        # 记录管理员操作日志
        LogEntry.objects.log_action(
            user_id=self.request.user.pk,
            content_type_id=ContentType.objects.get_for_model(User).pk,
            object_id=user.pk,
            object_repr=str(user),
            action_flag=CHANGE,
            change_message='投票已重置',
        )

        messages.success(self.request, "投票已成功重置")
        return redirect(self.get_success_url())
