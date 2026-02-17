from django.http import HttpRequest

from renderer.utils import render_user_to_json
from . import APIView

from web.controllers import search, articles


class SearchView(APIView):
    """文章搜索API视图
    作用：处理文章搜索请求，支持关键词搜索、分页、源码/正文搜索模式，返回格式化的搜索结果和摘要
    """
    def get(self, request: HttpRequest):
        """处理搜索请求
        URL参数说明：
        - text: 搜索关键词（必填）
        - cursor: 分页游标（可选）
        - mode: 搜索模式（plain=正文搜索，source=源码搜索，默认plain）
        - limit: 每页结果数（1-25，默认25）
        """
        # 提取并标准化搜索参数
        search_query = request.GET.get('text', '')  # 搜索关键词
        cursor = request.GET.get('cursor')          # 分页游标
        search_mode = request.GET.get('mode', 'plain')  # 搜索模式
        
        # 验证并限制每页结果数（1-25之间）
        try:
            limit = int(request.GET.get('limit', '25'))
            if limit < 1:
                limit = 1
            if limit > 25:
                limit = 25
        except ValueError:
            limit = 25
        
        # 执行文章搜索（区分正文/源码搜索）
        results, next_cursor = search.search_articles(
            search_query, 
            is_source=(search_mode == 'source'), 
            cursor=cursor, 
            limit=limit
        )
        
        # 格式化搜索结果
        output_results = []
        for result in results:
            article = result['article'].article
            # 获取文章评分数据
            rating, votes, popularity, mode = articles.get_rating(article)
            # 格式化作者信息
            authors = [render_user_to_json(author) for author in article.authors.all()]
            
            output_results.append({
                'uid': article.id,
                'pageId': article.full_name,
                'title': article.title,
                'createdAt': article.created_at.isoformat(),
                'updatedAt': article.updated_at.isoformat(),
                'createdBy': authors[0],
                'authors': authors,
                'rating': {
                    'value': rating,
                    'votes': votes,
                    'popularity': popularity,
                    'mode': str(mode)
                },
                'tags': articles.get_tags(article),
                'words': result['words'],          # 匹配的关键词列表
                'excerpts': self.get_excerpts(result, search_mode == 'source')  # 搜索摘要
            })
        
        # 返回分页搜索结果
        return self.render_json(200, {
            'results': output_results,
            'cursor': next_cursor
        })

    @classmethod
    def get_excerpts(cls, result, is_source):
        """提取搜索结果的相关摘要
        :param result: 单条搜索结果
        :param is_source: 是否为源码搜索模式
        :return: 格式化后的摘要列表
        """
        # 1. 获取要提取摘要的原文内容（源码/纯文本）
        original = result['article'].content_source if is_source else result['article'].content_plaintext
        # 分割内容（忽略第一段，通常为标题/简介）
        original = original.split('\n\n', 1)
        if len(original) < 2:
            return []
        original = original[1]
        original_to_search = original.lower()  # 转为小写用于匹配
        
        # 2. 整理要匹配的关键词（去重，按长度倒序排列）
        words_to_search = list(sorted({x.lower() for x in result['words']}, key=lambda x: len(x), reverse=True))
        
        # 3. 配置摘要提取参数
        ranges = []                  # 摘要位置区间列表
        offset = 30                  # 关键词前后偏移字符数
        word_length_cutoff = 2       # 最小关键词长度阈值
        # 判断是否存在长关键词（长度>2）
        has_long_words = bool([x for x in words_to_search if len(x) > word_length_cutoff])
        
        # 4. 查找所有关键词的位置并生成摘要区间
        for word in words_to_search:
            # 有长关键词时，忽略短关键词（避免无意义的"in"/"with"等）
            if has_long_words and len(word) <= word_length_cutoff:
                continue
            # 查找关键词在文本中的所有位置
            word_positions = cls.findall(word, original_to_search)
            for position in word_positions:
                # 计算关键词的起止位置，并扩展偏移量
                word_start = position
                word_end = len(word) + word_start
                word_start = max(0, word_start - offset)    # 避免越界
                word_end = min(len(original_to_search), word_end + offset)
                # 存储（关键词长度, 起始位置, 结束位置）
                ranges.append((len(word), word_start, word_end))
        
        # 5. 合并重叠的摘要区间
        ranges.sort(key=lambda x: x[1])  # 按起始位置排序
        i = 0
        while i < len(ranges) - 1:
            if ranges[i+1][1] < ranges[i][2]:
                # 区间重叠：合并区间，删除下一个区间
                ranges[i] = (max(ranges[i][0], ranges[i+1][0]), ranges[i][1], ranges[i+1][2])
                del ranges[i+1]
                continue
            i += 1
        
        # 6. 排序并限制摘要数量（优先长关键词，最多25条）
        # 按关键词长度降序、起始位置升序排序
        ranges.sort(key=lambda x: (-x[0], x[1]), reverse=False)
        ranges = ranges[:25]
        
        # 7. 提取摘要文本
        excerpts = []
        for _, excerpt_start, excerpt_end in ranges:
            excerpts.append(original[excerpt_start:excerpt_end])
        
        # 8. 限制返回的摘要总长度（避免数据过大）
        max_excerpt_len = 1024
        combined_len = 0
        for i in range(len(excerpts)):
            combined_len += len(excerpts[i])
            if combined_len > max_excerpt_len:
                return excerpts[:i]
        
        return excerpts

    @classmethod
    def findall(cls, p, s):
        """查找字符串中指定子串的所有位置
        :param p: 要查找的子串（关键词）
        :param s: 目标字符串
        :return: 子串所有起始位置的列表
        注：暂未处理子串作为其他单词一部分的情况
        """
        i = s.find(p)
        positions = []
        while i != -1:
            positions.append(i)
            i = s.find(p, i + 1)  # 从下一个位置继续查找
        return positions
