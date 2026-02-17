from solo.admin import SingletonModelAdmin
from adminsortable2.admin import SortableAdminMixin

from django.db.models.query import QuerySet
from django.db.models import ExpressionWrapper, F, Case, When, BooleanField
from django.contrib.admin import SimpleListFilter
from django.contrib.auth.models import Permission
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import UserChangeForm
from django.contrib import admin
from django.urls import path
from django import forms

import web.fields
from web.views.sus_users import AdminSusActivityView

from .models import *
from .fields import CITextField
from .views.invite import InviteView
from .views.bot import CreateBotView
from .views.reset_votes import ResetUserVotesView
from .controllers import logging
from .permissions import get_role_permissions_content_type


class TagsCategoryForm(forms.ModelForm):
    """标签分类表单"""
    class Meta:
        model = TagsCategory
        widgets = {
            'name': forms.TextInput,
            'slug': forms.TextInput,
        }
        fields = ('name', 'slug', 'description', 'priority')


@admin.register(TagsCategory)
class TagsCategoryAdmin(admin.ModelAdmin):
    """标签分类后台管理配置"""
    form = TagsCategoryForm
    search_fields = ['name', 'slug', 'description']
    list_display = ['name', 'description', 'priority', 'slug']


class TagForm(forms.ModelForm):
    """标签表单"""
    class Meta:
        model = Tag
        widgets = {
            'name': forms.TextInput
        }
        fields = '__all__'


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    """标签后台管理配置"""
    form = TagForm
    search_fields = ['name', 'category__name']
    list_filter = ['category']
    list_display = ['name', 'category']


class SettingsForm(forms.ModelForm):
    """系统设置表单"""
    class Meta:
        model = Settings
        widgets = {
            'rating_mode': forms.Select
        }
        fields = '__all__'
        exclude = ['site', 'category']


class SettingsAdmin(admin.StackedInline):
    """系统设置内嵌管理配置"""
    form = SettingsForm
    model = Settings
    can_delete = False
    max_num = 1


class CategoryForm(forms.ModelForm):
    """分类表单（含权限重写逻辑）"""
    class Meta:
        model = Category
        widgets = {
            'name': forms.TextInput,
        }
        exclude = ['permissions_override']

    _add_override_roles_ = forms.ModelMultipleChoiceField(
        label='添加需重写权限的角色', 
        queryset=QuerySet(Role), 
        required=False
    )
    _remove_override_roles_ = forms.ModelMultipleChoiceField(
        label='移除权限重写的角色', 
        queryset=QuerySet(Role), 
        required=False
    )
    _perms_override_ = web.fields.PermissionsOverrideField(exclude_admin=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        instance = kwargs.get('instance')
        if instance:
            self.fields['_perms_override_'].widget.instance = instance

            # 获取已配置权限重写的角色，用于区分添加/移除的角色列表
            overrided_roles = Role.objects.filter(rolepermissionsoverride__in=instance.permissions_override.all())
            self.fields['_add_override_roles_'].queryset = Role.objects.exclude(id__in=overrided_roles)
            self.fields['_remove_override_roles_'].queryset = overrided_roles
        else:
            self.fields['_perms_override_'].widget.instance = None
            self.fields['_add_override_roles_'].queryset = Role.objects.all()
            self.fields['_remove_override_roles_'].disabled = True

    def save(self, commit=True):
        """重写保存逻辑：处理角色权限重写的添加/移除"""
        instance = super().save(commit=False)
        instance.save()

        # 处理权限重写配置
        roles_data = self.cleaned_data.get('_perms_override_', {})
        if roles_data:
            content_type = get_role_permissions_content_type()
            overrides = []

            # 先清空原有权限重写配置
            instance.permissions_override.all().delete()

            # 批量创建新的权限重写记录
            for role_id, perms_data in roles_data.items():
                perms_override = RolePermissionsOverride.objects.create(role_id=role_id)

                if perms_data['allow']:
                    perms = Permission.objects.filter(codename__in=perms_data['allow'], content_type=content_type)
                    perms_override.permissions.set(perms)

                if perms_data['deny']:
                    restrictions = Permission.objects.filter(codename__in=perms_data['deny'], content_type=content_type)
                    perms_override.restrictions.set(restrictions)

                overrides.append(perms_override)

            instance.permissions_override.add(*overrides)

        # 处理添加需重写权限的角色
        roles_to_override = self.cleaned_data.get('_add_override_roles_', {})
        if roles_to_override:
            overrides = []
            for role in roles_to_override:
                overrides.append(RolePermissionsOverride.objects.create(role=role))
            instance.permissions_override.add(*overrides)

        # 处理移除权限重写的角色
        roles_to_cancel_override = self.cleaned_data.get('_remove_override_roles_', {})
        if roles_to_cancel_override:
            instance.permissions_override.all().filter(role__in=roles_to_cancel_override).delete()

        if commit:
            instance.save()

        return instance


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    """分类后台管理配置"""
    form = CategoryForm
    fieldsets = (
        (None, {
            'fields': ('name', 'is_indexed')
        }),
        ('权限重写', {
            'fields': ('_add_override_roles_', '_remove_override_roles_', '_perms_override_')
        })
    )
    inlines = [SettingsAdmin]


class SiteForm(forms.ModelForm):
    """站点配置表单"""
    class Meta:
        model = Site
        widgets = {
            'slug': forms.TextInput,
            'title': forms.TextInput,
            'headline': forms.TextInput,
            'domain': forms.TextInput,
            'media_domain': forms.TextInput
        }
        fields = '__all__'


@admin.register(Site)
class SiteAdmin(SingletonModelAdmin):
    """站点配置后台管理（单例模型）"""
    form = SiteForm
    inlines = [SettingsAdmin]
    fields = ['slug', 'title', 'headline', 'domain', 'media_domain']

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)


class ForumSectionForm(forms.ModelForm):
    """论坛板块表单"""
    class Meta:
        model = ForumSection
        widgets = {
            'name': forms.TextInput,
        }
        fields = '__all__'


@admin.register(ForumSection)
class ForumSectionAdmin(admin.ModelAdmin):
    """论坛板块后台管理配置"""
    form = ForumSectionForm
    search_fields = ['name', 'description']


class ForumCategoryForm(forms.ModelForm):
    """论坛分类表单"""
    class Meta:
        model = ForumCategory
        widgets = {
            'name': forms.TextInput,
        }
        fields = '__all__'


@admin.register(ForumCategory)
class ForumCategoryAdmin(admin.ModelAdmin):
    """论坛分类后台管理配置"""
    form = ForumCategoryForm
    search_fields = ['name', 'description']
    list_filter = ['section']
    list_display = ['name', 'section']


class AdvancedUserChangeForm(UserChangeForm):
    """增强版用户编辑表单（修复输入框样式+角色筛选）"""
    class Meta:
        # 修复username和wikidot_username输入框样式
        widgets = {
            'username': forms.TextInput(attrs={'class': 'vTextField'}),
            'wikidot_username': forms.TextInput(attrs={'class': 'vTextField'})
        }

    # _op_index = forms.CharField(
    #     label='权限等级',
    #     help_text='显示优先级最高的角色索引，值越小优先级越高'
    # )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # 排除默认角色（everyone/registered）不显示在编辑界面
        if 'roles' in self.fields:
            self.fields['roles'].queryset = Role.objects.exclude(slug__in=['everyone', 'registered'])


@admin.register(User)
class AdvancedUserAdmin(ProtectsensitiveAdminMixin, UserAdmin):
    """增强版用户后台管理配置（含权限控制+自定义URL）"""
    form = AdvancedUserChangeForm

    list_filter = ['is_superuser', 'is_active', 'roles']
    list_display = ['username_or_wd', 'email', 'is_active']
    search_fields = ['username', 'wikidot_username', 'email']
    readonly_fields = ['api_key', '_op_index']
    sensitive_fields = ['email']

    # 重写字段分组
    fieldsets = UserAdmin.fieldsets
    fieldsets[0][1]['fields'] = ('username', 'wikidot_username', 'type', 'password', 'api_key', '_op_index')
    fieldsets[1][1]['fields'] += ('bio', 'avatar')
    fieldsets[2][1]['fields'] = ('is_active', 'inactive_until', 'is_forum_active', 'forum_inactive_until', 'roles', 'is_superuser')

    @admin.display(ordering='username_or_wd')
    def username_or_wd(self, obj):
        """显示用户名（优先显示Wikidot用户名）"""
        return obj.__str__()
    
    @admin.display(description='权限等级')
    def _op_index(self, obj):
        """显示用户的权限索引值"""
        return obj.operation_index

    def get_urls(self):
        """添加自定义后台URL（邀请/创建机器人/激活用户/重置投票）"""
        urls = super().get_urls()
        new_urls = [
            path('invite/', InviteView.as_view()),
            path('newbot/', CreateBotView.as_view()),
            path('<id>/activate/', InviteView.as_view()),
            path('<id>/reset_votes/', ResetUserVotesView.as_view()),
        ]
        return new_urls + urls

    def get_form(self, request, *args, **kwargs):
        """设置部分字段为非必填"""
        form = super().get_form(request, *args, **kwargs)
        not_required = ['inactive_until', 'forum_inactive_until', 'wikidot_username']
        for not_required_field in not_required:
            if not_required_field in form.base_fields:
                form.base_fields[not_required_field].required = False
        return form

    def get_readonly_fields(self, request, obj=None):
        """非超级管理员无法编辑is_superuser字段"""
        readonly_fields = super().get_readonly_fields(request, obj)
        if not request.user.is_superuser:
            readonly_fields += ['is_superuser']
        return readonly_fields
    
    def get_queryset(self, request):
        """优化查询集：添加用户名别名排序"""
        qs = super(AdvancedUserAdmin, self).get_queryset(request)
        return qs.annotate(
                username_or_wd=ExpressionWrapper(
                    Case(
                        When(type=User.UserType.Wikidot, then=F('wikidot_username')),
                        default=F('username'),
                        output_field=CITextField()
                    ),
                    output_field=CITextField()
                )
            ).order_by('username_or_wd')

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        """无角色管理权限的用户无法编辑角色字段"""
        if db_field.name == 'roles' and not request.user.has_perm('roles.manage_roles'):
            kwargs['disabled'] = True
        return super().formfield_for_manytomany(db_field, request, **kwargs)
    
    def has_change_permission(self, request, obj=None):
        """权限控制：普通管理员无法编辑权限等级高于/等于自己的用户"""
        if obj and not request.user.is_superuser and obj.operation_index <= request.user.operation_index:
            return False
        return super().has_change_permission(request, obj)
    
    def save_model(self, request, obj, form, change):
        """保存时的权限控制：防止普通管理员修改超级管理员状态/角色"""
        if obj.pk:
            target = User.objects.get(id=obj.id)
            if change:
                # 非超级管理员无法修改超级管理员状态
                if not request.user.is_superuser:
                    obj.is_superuser = target.is_superuser
                # 无角色管理权限的用户无法修改角色
                if not request.user.has_perm('roles.manage_roles'):
                    obj.roles.set(target.roles.all())
        super().save_model(request, obj, form, change)


class ActionsLogForm(forms.ModelForm):
    """操作日志表单"""
    class Meta:
        model = ActionLogEntry
        exclude = ['meta']


@admin.register(ActionLogEntry)
class ActionsLogAdmin(ProtectsensitiveAdminMixin, admin.ModelAdmin):
    """操作日志后台管理（只读）"""
    form = ActionsLogForm
    list_filter = ['user', 'type', 'created_at', 'origin_ip']
    list_display = ['user_or_name', 'type', 'info', 'created_at', 'origin_ip']
    search_fields = ['meta']
    sensitive_fields = ['origin_ip']

    @admin.display(description=User._meta.verbose_name)  # 修正原代码的Meta拼写错误
    def user_or_name(self, obj):
        """显示操作用户（已删除用户显示历史用户名）"""
        if obj.user is None:
            return f'{obj.stale_username} (已删除)'
        return obj.user
    
    @admin.display(description='详细信息')
    def info(self, obj):
        """显示日志的详细描述"""
        return logging.get_action_log_entry_description(obj)

    def has_add_permission(self, request):
        """禁止添加日志"""
        return False

    def has_delete_permission(self, request, obj=None):
        """禁止删除日志"""
        return False
    
    def has_change_permission(self, request, obj=None):
        """禁止修改日志"""
        return False
    
    def get_urls(self):
        """添加可疑行为查看URL"""
        urls = super().get_urls()
        new_urls = [
            path('sus', AdminSusActivityView.as_view())
        ]
        return new_urls + urls


class RoleCategoryForm(forms.ModelForm):
    """角色分类表单"""
    class Meta:
        model = RoleCategory
        fields = '__all__'


@admin.register(RoleCategory)
class RoleCategoryAdmin(admin.ModelAdmin):
    """角色分类后台管理配置"""
    form = RoleCategoryForm


class RoleForm(forms.ModelForm):
    """角色表单（含权限配置）"""
    class Meta:
        model = Role
        exclude = ['permissions', 'restrictions']

    _perms_ = web.fields.PermissionsField()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        instance = kwargs.get('instance')
        self.fields['_perms_'].widget.instance = instance

    def save(self, commit=True):
        """重写保存逻辑：处理角色权限/限制配置"""
        instance = super().save(commit=False)
        instance.save()

        perms_data = self.cleaned_data.get('_perms_', {})
        if perms_data:
            content_type = get_role_permissions_content_type()

            # 清空原有权限/限制
            instance.permissions.clear()
            instance.restrictions.clear()

            # 设置允许的权限
            if perms_data['allow']:
                perms = Permission.objects.filter(codename__in=perms_data['allow'], content_type=content_type)
                instance.permissions.set(perms)

            # 设置禁止的权限
            if perms_data['deny']:
                restrictions = Permission.objects.filter(codename__in=perms_data['deny'], content_type=content_type)
                instance.restrictions.set(restrictions)

        if commit:
            instance.save()

        return instance


class IsVisualRoleFilter(SimpleListFilter):
    """自定义筛选器：是否为可视化角色"""
    title = '可视化角色'
    parameter_name = 'is_visual_role'

    def lookups(self, request, model_admin):
        return [
            (True, '是'),
            (False, '否')
        ]

    def queryset(self, request, queryset):
        """筛选逻辑：判断角色是否有可视化配置"""
        if self.value():
            return queryset.annotate(is_visual_role=ExpressionWrapper(
                F('group_votes') or \
                F('inline_visual_mode') != Role.InlineVisualMode.Hidden or \
                F('profile_visual_mode') != Role.ProfileVisualMode.Hidden,
                output_field=BooleanField()
            )).filter(is_visual_role=self.value())
        else:
            return queryset

@admin.register(Role)
class RoleAdmin(SortableAdminMixin, admin.ModelAdmin):
    """角色后台管理配置（支持排序+可视化筛选）"""
    form = RoleForm
    list_filter = ['category', 'is_staff', IsVisualRoleFilter]
    list_display = ['__str__', '_users_number', '_idx']
    fieldsets = (
        (None, {
            'fields': ('slug', 'name', 'short_name', 'category', 'is_staff')
        }),
        ('可视化配置', {
            'fields': ('group_votes', 'votes_title', 'inline_visual_mode', 'profile_visual_mode', 'color', 'icon', 'badge_text', 'badge_bg', 'badge_text_color', 'badge_show_border')
        }),
        ('访问权限', {
            'fields': ('_perms_',)
        })
    )

    @admin.display(description='索引')
    def _idx(self, obj):
        """显示角色的索引值"""
        return obj.index

    @admin.display(description='用户数量')
    def _users_number(self, obj):
        """显示拥有该角色的用户数量（默认角色显示总用户数）"""
        if obj.slug in ['everyone', 'registered']:
            return User.objects.all().count()
        return obj.users.all().count()
    
    @property
    def change_list_template(self):
        """自定义列表模板路径"""
        return 'admin/%s/%s/change_list.html' % (self.opts.app_label, self.opts.model_name)
    
    @property
    def change_list_results_template(self):
        """自定义列表结果模板路径"""
        return 'admin/%s/%s/change_list_results.html' % (self.opts.app_label, self.opts.model_name)
    
    def has_delete_permission(self, request, obj=None):
        """禁止删除默认角色（everyone/registered）"""
        if obj and obj.slug in ['everyone', 'registered']:
            return False
        return super().has_delete_permission(request, obj)
    
    def has_change_permission(self, request, obj=None):
        """权限控制：普通管理员无法编辑索引值高于自己的角色"""
        if obj and not request.user.is_superuser and obj.index < request.user.operation_index:
            return False
        return super().has_change_permission(request, obj)
        
    def get_readonly_fields(self, request, obj=None):
        """默认角色的slug字段只读"""
        if obj and obj.slug in ['everyone', 'registered']:
            return self.readonly_fields + ("slug",)
        return self.readonly_fields
