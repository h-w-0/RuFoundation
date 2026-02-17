from django import forms
from django.core.validators import RegexValidator

from web.models.roles import Role
from web.models.users import User


class UserProfileForm(forms.ModelForm):
    """用户资料编辑表单"""
    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'bio', 'avatar']
        widgets = {
            'username': forms.TextInput()
        }


class InviteForm(forms.Form):
    """用户邀请表单（后台管理员使用）"""
    # 隐藏字段：选中的用户ID（支持多选）
    _selected_user = forms.IntegerField(widget=forms.MultipleHiddenInput, required=False)
    # 邀请邮箱（适配Admin样式）
    email = forms.EmailField(widget=forms.EmailInput(attrs={'class': 'vTextField'}))
    # 分配的角色（排除默认角色everyone/registered）
    roles = forms.ModelMultipleChoiceField(
        label='角色', 
        queryset=Role.objects.exclude(slug__in=['everyone', 'registered']), 
        required=False
    )


class CreateAccountForm(forms.Form):
    """普通用户注册表单"""
    username = forms.CharField(
        label='用户名',
        required=True,
        validators=[
            # 用户名验证：仅允许字母、数字、下划线、横线
            RegexValidator(r'^[A-Za-z0-9_-]+$', '用户名格式无效，仅允许字母、数字、下划线和横线')
        ]
    )
    password = forms.CharField(label='密码', widget=forms.PasswordInput(), required=True)
    password2 = forms.CharField(label='确认密码', widget=forms.PasswordInput(), required=True)

    def clean_password2(self):
        """验证两次输入的密码是否一致"""
        cd = self.cleaned_data
        if cd['password'] != cd['password2']:
            raise forms.ValidationError('两次输入的密码不一致')
        return cd['password2']


class CreateBotForm(forms.Form):
    """创建机器人账号表单"""
    username = forms.CharField(
        label='机器人昵称',
        required=True,
        validators=[
            # 机器人昵称验证：仅允许字母、数字、下划线、横线
            RegexValidator(r'^[A-Za-z0-9_-]+$', '昵称格式无效，仅允许字母、数字、下划线和横线')
        ]
    )
