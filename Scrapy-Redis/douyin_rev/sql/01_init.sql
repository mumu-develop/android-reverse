-- douyin_rev 表结构（MySQL 版；SQLite 由 SQLAlchemy 自动建表）
-- 用法：mysql -u root -p douyin < sql/01_init.sql

CREATE DATABASE IF NOT EXISTS douyin DEFAULT CHARSET utf8mb4;
USE douyin;

-- 任务表：一行 = 一个用户主页
CREATE TABLE IF NOT EXISTS user_task (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    user_url        VARCHAR(512) NOT NULL COMMENT '抖音主页链接（含 sec_user_id）',
    sec_user_id     VARCHAR(128) NULL COMMENT 'MS4wLjABAAAA...',
    status          VARCHAR(16) NOT NULL DEFAULT 'pending'
                    COMMENT 'pending/running/paused/partial/completed/failed',
    priority        INT NOT NULL DEFAULT 0,
    assigned_worker VARCHAR(64) NULL,
    profile_done    TINYINT(1) NOT NULL DEFAULT 0,
    videos_done     TINYINT(1) NOT NULL DEFAULT 0,
    comments_done   TINYINT(1) NOT NULL DEFAULT 0,
    video_cursor    BIGINT NOT NULL DEFAULT 0 COMMENT '作品列表 max_cursor（毫秒时间戳）',
    video_pages     INT NOT NULL DEFAULT 0,
    video_index     INT NOT NULL DEFAULT 0 COMMENT '评论阶段：第几个视频',
    comment_aweme_id VARCHAR(64) NULL,
    comment_cursor  INT NOT NULL DEFAULT 0,
    comment_pages   INT NOT NULL DEFAULT 0,
    attempts        INT NOT NULL DEFAULT 0,
    last_error      VARCHAR(512) NULL,
    created_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                    ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_user_task_url (user_url),
    KEY idx_user_task_status_prio (status, priority)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='用户采集任务';

-- 用户详情
CREATE TABLE IF NOT EXISTS user_profile (
    id               INT AUTO_INCREMENT PRIMARY KEY,
    sec_user_id      VARCHAR(128) NOT NULL,
    uid              VARCHAR(64) NULL,
    unique_id        VARCHAR(64) NULL COMMENT '抖音号',
    short_id         VARCHAR(64) NULL,
    nickname         VARCHAR(255) NULL,
    signature        TEXT NULL,
    avatar_url       VARCHAR(1024) NULL,
    follower_count   BIGINT DEFAULT 0,
    following_count  BIGINT DEFAULT 0,
    aweme_count      BIGINT DEFAULT 0,
    total_favorited  BIGINT DEFAULT 0,
    fetched_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_user_profile_sec (sec_user_id),
    KEY idx_user_profile_uid (uid),
    KEY idx_user_profile_unique (unique_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='用户详情';

-- 作品（视频）列表
CREATE TABLE IF NOT EXISTS user_videos (
    id             INT AUTO_INCREMENT PRIMARY KEY,
    aweme_id       VARCHAR(64) NOT NULL,
    sec_user_id    VARCHAR(128) NOT NULL,
    desc           TEXT NULL,
    create_time    BIGINT DEFAULT 0,
    duration       INT DEFAULT 0,
    digg_count     BIGINT DEFAULT 0,
    comment_count  BIGINT DEFAULT 0,
    share_count    BIGINT DEFAULT 0,
    collect_count  BIGINT DEFAULT 0,
    play_url       VARCHAR(1024) NULL,
    cover_url      VARCHAR(1024) NULL,
    fetched_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_user_videos_aweme (aweme_id),
    KEY idx_user_videos_sec (sec_user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='用户作品列表';

-- 视频评论
CREATE TABLE IF NOT EXISTS user_video_comments (
    id           INT AUTO_INCREMENT PRIMARY KEY,
    cid          VARCHAR(64) NOT NULL,
    aweme_id     VARCHAR(64) NOT NULL,
    text         TEXT NULL,
    create_time  BIGINT DEFAULT 0,
    digg_count   BIGINT DEFAULT 0,
    reply_total  INT DEFAULT 0,
    uid          VARCHAR(64) NULL,
    nickname     VARCHAR(255) NULL,
    sec_uid      VARCHAR(128) NULL,
    fetched_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_comments_cid (cid),
    KEY idx_comments_aweme (aweme_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='视频评论';
