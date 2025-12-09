# 文章修订格式

我们的修订版本目前采用自由格式的 JSONB 进行编码。

未来可能会对该格式进行调整；为确保当前文档的规范性，特此整理本文档作为参考。

每个修订版本均为 `ArticleLogEntry` 的实例，因此均包含以下公共字段：

- Article ID（文章ID）
- User ID（用户ID）
- Revision type（修订类型）
- Revision metadata（修订元数据，详见下文）
- Date（日期）
- Comment（备注）
- Revision index（修订索引，属于当前文章）

目前支持的修订类型如下：

- `LogEntryType.Source`：源代码修改
- `LogEntryType.Title`：标题修改
- `LogEntryType.Name`：别名（URL、pageId）修改
- `LogEntryType.Tags`：标签列表修改
- `LogEntryType.New`：标记页面创建的正式修订版本
- `LogEntryType.Parent`：父页面修改
- `LogEntryType.FileAdded`：文件添加
- `LogEntryType.FileDeleted`：文件删除
- `LogEntryType.FileRenamed`：文件重命名
- `LogEntryType.VotesDeleted`：投票记录删除
- `LogEntryType.Wikidot`：Wikidot 修订版本；无实际功能，不可撤销，仅包含备注（用于历史回顾）
- `LogEntryType.Revert`：撤销修订（回滚操作）

每种修订类型的元数据字段格式各不相同，具体说明如下：

## `LogEntryType.Source`（源代码修改）

```javascript
{
  "version_id": int /* ArticleVersion ID（文章版本ID） */
}
```

## `LogEntryType.Title`（标题修改）

```javascript
{
  "title": string, /* 新标题 */
  "prev_title": string /* 旧标题 */
}
```

## `LogEntryType.Name`（别名修改）

```javascript
{
  "name": string, /* 全新别名（含分类） */
  "prev_name": string /* 原别名（含分类） */
}
```

## `LogEntryType.Tags`（标签列表修改）

```javascript
{
  "added_tags": [{ /* 新增标签列表 */
    "id": int, /* Tag ID（标签ID） */
    "name": string /* 标签全称（含分类）；仅用于显示 */
  }],
  "removed_tags": [{ /* 移除标签列表 */
    "id": int, /* Tag ID（标签ID） */
    "name": string /* 标签全称（含分类）；仅用于显示 */
  }]
}
```

## `LogEntryType.New`（页面创建）

以下字段通常仅用于追踪记录，不参与实际功能逻辑。

原因：撤销修订的操作本质是反向执行修改，而“页面创建”这一修订无法被撤销。

```javascript
{
  "version_id": int, /* ArticleVersion ID（文章版本ID） */ 
  "title": string /* 文章初始标题 */
}
```

## `LogEntryType.Parent`（父页面修改）

```javascript
{
  "parent": string, /* 新父页面别名（含分类）；仅用于显示 */
  "prev_parent": string, /* 原父页面别名（含分类）；仅用于显示 */
  "parent_id": int, /* 新父页面的 Article ID（文章ID） */
  "prev_parent_id": int /* 原父页面的 Article ID（文章ID） */
}
```

## `LogEntryType.FileAdded`（文件添加）

```javascript
{
  "id": int, /* File ID（文件ID） */
  "name": string /* 文件名 */
}
```

## `LogEntryType.FileDeleted`（文件删除）

```javascript
{
  "id": int, /* File ID（文件ID） */
  "name": string /* 文件名 */
}
```

## `LogEntryType.FileRenamed`（文件重命名）

```javascript
{
  "id": int, /* File ID（文件ID） */
  "name": string, /* 新文件名 */
  "prev_name": string /* 原文件名 */
}
```

## `LogEntryType.VotesDeleted`（投票记录删除）

系统会存储删除时已存在的所有投票数据。

```javascript
{
  "rating_mode": string, /* Settings.RatingMode 枚举（评分模式） */
  "rating": int | float, /* 评分值（总和或平均值，取决于评分模式） */
  "votes_count": int, /* 投票总数 */
  "popularity": float, /* 热度值 */
  "votes": [{ /* 投票详情列表 */
    "user_id": int, /* User ID（投票用户ID） */
    "vote": int | float, /* 投票分值（1/-1 或 0-5的浮点数，取决于评分模式） */
    "visual_group_id": int | null, /* VisualUserGroup ID（用户可视化组ID，可为空） */
    "date": string /* ISO 8601格式的日期时间 */
  }]
}
```

## `LogEntryType.Revert`（撤销修订）

注：元数据字段的存在与否，取决于具体的撤销子类型。

```javascript
{
  "subtypes": [string], /* LogEntryType 枚举（被撤销的修订类型列表） */
  "rev_number": int, /* 目标回滚版本的修订索引 */
  /* 仅在包含文件相关子类型时存在 */
  "files": {
    /* 仅在子类型包含 FileAdded 时存在 */
    "added": [{
      "id": int, /* File ID（文件ID） */
      "name": string /* 文件名 */
    }],
    /* 仅在子类型包含 FileDeleted 时存在 */
    "deleted": [{
      "id": int, /* File ID（文件ID） */
      "name": string /* 文件名 */
    }],
    /* 仅在子类型包含 FileRenamed 时存在 */
    "renamed": [{
      "id": int, /* File ID（文件ID） */
      "name": string, /* 新文件名 */
      "prev_name": string /* 原文件名 */
    }]
  },
  /* 仅在子类型包含 Tags 时存在 */
  "tags": {
    "added": [int], /* 新增标签的 Tag ID（标签ID）列表 */
    "removed": [int] /* 移除标签的 Tag ID（标签ID）列表 */
  },
  /* 仅在子类型包含 Source 时存在 */
  "source": {
    "version_id": int /* ArticleVersion ID（文章版本ID） */
  },
  /* 仅在子类型包含 Title 时存在 */
  "title": {
    "title": string, /* 新标题 */
    "prev_title": string /* 原标题 */
  },
  /* 仅在子类型包含 Name 时存在 */
  "name": {
    "name": string, /* 全新别名（含分类） */
    "prev_name": string /* 原别名（含分类） */
  },
  /* 仅在子类型包含 Parent 时存在 */
  "parent": {
    "parent": string, /* 新父页面别名（含分类）；仅用于显示 */
    "prev_parent": string, /* 原父页面别名（含分类）；仅用于显示 */
    "parent_id": int, /* 新父页面的 Article ID（文章ID） */
    "prev_parent_id": int /* 原父页面的 Article ID（文章ID） */
  },
  /* 仅在子类型包含 Votes 时存在 */
  "votes": {
    "rating_mode": string, /* Settings.RatingMode 枚举（评分模式） */
    "rating": int | float, /* 评分值（总和或平均值，取决于评分模式） */
    "votes_count": int, /* 投票总数 */
    "popularity": float, /* 热度值 */
    "votes": [{ /* 投票详情列表 */
      "user_id": int, /* User ID（投票用户ID） */
      "vote": int | float, /* 投票分值（1/-1 或 0-5的浮点数，取决于评分模式） */
      "visual_group_id": int | null, /* VisualUserGroup ID（用户可视化组ID，可为空） */
      "date": string /* ISO 8601格式的日期时间 */
    }]
  }
}
```
