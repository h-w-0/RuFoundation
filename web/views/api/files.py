from django.conf import settings
from django.db.models import Sum
from django.http import HttpRequest
import os.path
from uuid import uuid4

from renderer.utils import render_user_to_json
from . import APIView, APIError, takes_json

from web.controllers import articles
import urllib.parse

from ...models.files import File


class FileView(APIView):
    """文件管理基础API视图（提供通用验证逻辑）"""
    @staticmethod
    def _validate_request(request: HttpRequest, article_name_or_article, edit=True):
        """验证文件操作的请求合法性
        :param request: 当前请求对象
        :param article_name_or_article: 文章名称/文章对象
        :param edit: 是否为编辑类操作（上传/重命名/删除），True时验证文件管理权限
        :return: 验证通过的文章对象
        :raise APIError: 权限不足/文章不存在时抛出异常
        """
        article = articles.get_article(article_name_or_article)
        if article is None:
            # 即使文章不存在，也验证查看权限（防止枚举）
            category = articles.get_article_category(article_name_or_article)
            if not request.user.has_perm('roles.view_articles', category):
                raise APIError('权限不足', 403)
            raise APIError('页面不存在', 404)
        # 编辑操作需验证文件管理权限
        if edit and not request.user.has_perm('roles.manage_article_files', article):
            raise APIError('权限不足', 403)
        return article


class GetOrUploadView(FileView):
    """文件查询/上传API视图"""
    def get(self, request: HttpRequest, article_name):
        """获取指定文章下的所有文件及存储使用情况"""
        # 验证文章查看权限
        category = articles.get_article_category(article_name)
        if not request.user.has_perm('roles.view_articles', category):
            raise APIError('权限不足', 403)
        # 验证文章存在性（仅查看，不验证编辑权限）
        article = self._validate_request(request, article_name, edit=False)
        # 获取文章关联的所有文件
        files = articles.get_files_in_article(article)
        output = []
        # 获取文件存储使用量（软限制/硬限制）
        current_files_size, absolute_files_size = articles.get_file_space_usage()
        
        # 格式化文件列表数据
        for file in files:
            output.append({
                'id': file.id, 
                'name': file.name, 
                'size': file.size, 
                'createdAt': file.created_at, 
                'author': render_user_to_json(file.author), 
                'mimeType': file.mime_type
            })
        
        # 构造响应数据
        data = {
            'pageId': article.full_name,
            'files': output,
            'softLimit': settings.MEDIA_UPLOAD_LIMIT,          # 文件上传软限制（总大小）
            'hardLimit': settings.ABSOLUTE_MEDIA_UPLOAD_LIMIT, # 文件上传硬限制（总大小）
            'softUsed': current_files_size,                    # 当前已使用软限制空间
            'hardUsed': absolute_files_size                    # 当前已使用硬限制空间
        }
        return self.render_json(200, data)

    def post(self, request: HttpRequest, article_name):
        """上传文件到指定文章"""
        # 验证文章存在性及文件管理权限
        article = self._validate_request(request, article_name)
        
        # 1. 获取并验证文件名
        file_name = request.headers.get('x-file-name')
        if not file_name:
            raise APIError('缺少文件名', 400)
        # 解码URL编码的文件名
        file_name = urllib.parse.unquote(file_name)
        # 检查同名下的文件是否已存在
        existing_file = articles.get_file_in_article(article, file_name)
        if existing_file:
            raise APIError('该文件名已存在', 409)
        
        # 2. 生成唯一的媒体文件名称（避免冲突）
        _, ext = os.path.splitext(file_name)
        media_name = str(uuid4()) + ext
        # 创建文件记录（未保存）
        new_file = File(
            name=file_name, 
            media_name=media_name, 
            author=request.user, 
            article=article
        )
        
        # 3. 确保存储目录存在
        local_media_dir = os.path.dirname(new_file.local_media_path)
        if not os.path.exists(local_media_dir):
            os.makedirs(local_media_dir, exist_ok=True)
        
        # 4. 读取并保存文件（分块上传，实时检查大小限制）
        current_files_size, absolute_files_size = articles.get_file_space_usage()
        try:
            size = 0
            with open(new_file.local_media_path, 'wb') as f:
                while True:
                    # 分块读取（每块100KB）
                    chunk = request.read(102400)
                    size += len(chunk)
                    
                    # 检查文件大小限制（软限制/硬限制）
                    if (settings.MEDIA_UPLOAD_LIMIT > 0 and current_files_size + size > settings.MEDIA_UPLOAD_LIMIT) or \
                            (settings.ABSOLUTE_MEDIA_UPLOAD_LIMIT > 0 and absolute_files_size + size > settings.ABSOLUTE_MEDIA_UPLOAD_LIMIT):
                        raise APIError('文件上传大小超出限制', 413)
                    
                    # 读取完毕退出循环
                    if not chunk:
                        break
                    f.write(chunk)
            
            # 5. 保存文件元数据并关联到文章
            new_file.size = size
            new_file.mime_type = request.headers.get('content-type', 'application/octet-stream')
            articles.add_file_to_article(article, new_file, user=request.user)
        
        except Exception:
            # 上传失败时清理临时文件
            if os.path.exists(new_file.local_media_path):
                os.unlink(new_file.local_media_path)
            raise
        
        return self.render_json(200, {'status': 'ok'})


class RenameOrDeleteView(FileView):
    """文件重命名/删除API视图"""
    @staticmethod
    def _get_file_and_article(file_id):
        """根据文件ID获取关联的文章和文件对象
        :param file_id: 文件ID
        :return: (文章对象, 文件对象)，文件不存在时返回(None, None)
        """
        try:
            file = File.objects.get(id=file_id)
        except File.DoesNotExist:
            return None, None
        return file.article, file

    def delete(self, request: HttpRequest, file_id):
        """删除指定文件"""
        # 获取文件及关联文章
        article, file = self._get_file_and_article(file_id)
        # 验证文章权限
        article = self._validate_request(request, article)
        if file is None:
            raise APIError('文件不存在', 404)
        
        # 执行文件删除操作
        articles.delete_file_from_article(article, file, user=request.user)
        return self.render_json(200, {'status': 'ok'})

    @takes_json
    def put(self, request: HttpRequest, file_id):
        """重命名指定文件"""
        # 获取文件及关联文章
        article, file = self._get_file_and_article(file_id)
        # 验证文章权限
        article = self._validate_request(request, article)
        if file is None:
            raise APIError('文件不存在', 404)
        
        # 验证重命名参数
        data = self.json_input
        if not isinstance(data, dict) or 'name' not in data:
            raise APIError('无效的请求参数', 400)
        if not data['name']:
            raise APIError('缺少文件名', 400)
        
        # 检查新名称是否已存在
        existing_file = articles.get_file_in_article(article, data['name'])
        if existing_file and existing_file.id != file.id:
            raise APIError('该文件名已存在', 409)
        
        # 执行文件重命名
        articles.rename_file_in_article(article, file, data['name'], user=request.user)
        return self.render_json(200, {'status': 'ok'})
