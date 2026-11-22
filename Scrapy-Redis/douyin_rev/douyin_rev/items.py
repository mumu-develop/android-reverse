# -*- coding: utf-8 -*-
"""Item 定义（站点专属）。"""
import scrapy


class ProfileItem(scrapy.Item):
    """用户详情。"""
    sec_user_id = scrapy.Field()
    uid = scrapy.Field()
    unique_id = scrapy.Field()
    short_id = scrapy.Field()
    nickname = scrapy.Field()
    signature = scrapy.Field()
    avatar_url = scrapy.Field()
    follower_count = scrapy.Field()
    following_count = scrapy.Field()
    aweme_count = scrapy.Field()
    total_favorited = scrapy.Field()


class VideoItem(scrapy.Item):
    """作品（视频）列表一行。"""
    aweme_id = scrapy.Field()
    sec_user_id = scrapy.Field()
    desc = scrapy.Field()
    create_time = scrapy.Field()
    duration = scrapy.Field()
    digg_count = scrapy.Field()
    comment_count = scrapy.Field()
    share_count = scrapy.Field()
    collect_count = scrapy.Field()
    play_url = scrapy.Field()
    cover_url = scrapy.Field()


class CommentItem(scrapy.Item):
    """视频评论一行。"""
    cid = scrapy.Field()
    aweme_id = scrapy.Field()
    text = scrapy.Field()
    create_time = scrapy.Field()
    digg_count = scrapy.Field()
    reply_total = scrapy.Field()
    uid = scrapy.Field()
    nickname = scrapy.Field()
    sec_uid = scrapy.Field()
