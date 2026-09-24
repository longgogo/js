# coding=utf-8
# !/usr/bin/python
# 袋鼠影视 (https://dsystv.com) TVBox Python 爬虫源
# 按电影猎手(py.py)框架编写, 并加入全方法异常保护(防 TVBox 转圈)
#
# 站点结构(实测):
#   列表:   /search.php?searchtype=5&tid={tid}&page={pg}  条目 class="videopic" + img.lazy(data-original) + span.note备注 + span.score评分
#   详情:   /movie/index{id}.html  线路面板 data-playlist-name/line, 选集 <li id=N><a title="第XX集" href="/play/{id}-{s}-{n}.html">
#   选集兜底: /playlist.php?id={id}&line={n}  返回 <li> 片段
#   播放:   /play/{id}-{s}-{n}.html  内含 var now="m3u8直链"
#   搜索:   /search.php?searchword={kw}&searchtype=2&page={pg}
import re
import sys
import os
import time
from urllib.parse import quote, urljoin

# 影视仓加载 py 时工作目录不同, 必须先补路径再导入 base(与电影猎手 py.py 一致)
try:
    sys.path.append("..")
    sys.path.append(os.path.dirname(os.path.abspath(__file__)))
except Exception:
    pass

try:
    from base.spider import Spider
except Exception:
    # 兜底: 运行时未注入 base 包时, 提供最简网络基类
    import urllib.request as _ur

    class Spider(object):

        def fetch(self, url, headers=None, timeout=15, **kw):
            req = _ur.Request(url, headers=headers or {})
            with _ur.urlopen(req, timeout=timeout) as r:
                resp = type("Resp", (), {})()
                resp.text = r.read().decode("utf-8", "replace")
                resp.status_code = getattr(r, "status", 200)
                return resp


class Spider(Spider):

    HOST = "https://dsystv.com"
    UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
    _cache = {}
    _cache_time = {}

    # 分类映射(实测首页导航)
    CATS = [
        ("1", "电影"),
        ("5", "动作片"), ("10", "喜剧片"), ("7", "科幻片"), ("8", "恐怖片"),
        ("9", "战争片"), ("12", "剧情片"), ("6", "爱情片"), ("11", "纪录片"),
        ("41", "动画片"),
        ("2", "电视剧"),
        ("13", "国产剧"), ("14", "港台剧"), ("15", "欧美剧"), ("16", "日韩剧"),
        ("42", "海外剧"),
        ("3", "综艺"),
        ("4", "动漫"),
        ("44", "短剧"),
    ]

    def getName(self):
        return "袋鼠影视"

    def init(self, extend=""):
        self._cache = {}
        self._cache_time = {}

    # ---------- 缓存 ----------

    def _cache_get(self, key, ttl):
        try:
            t = self._cache_time.get(key, 0)
            if t and (time.time() - t) < ttl and key in self._cache:
                return self._cache[key]
        except Exception:
            pass
        return None

    def _cache_set(self, key, val):
        try:
            if len(self._cache) > 64:
                self._cache.clear()
                self._cache_time.clear()
            self._cache[key] = val
            self._cache_time[key] = time.time()
        except Exception:
            pass

    def isVideoFormat(self, url):
        return False

    def manualVideoCheck(self):
        return False

    def action(self, action):
        pass

    def destroy(self):
        pass

    def localProxy(self, param):
        return "[{}]"

    # ---------- 内部工具 ----------

    def header(self):
        return {"User-Agent": self.UA, "Referer": self.HOST + "/"}

    def _req(self, path):
        """带异常保护与 http 回退的请求, 失败返回空串, 绝不抛异常"""
        url = path
        if not url.startswith("http"):
            url = self.HOST + path
        urls = [url]
        if url.startswith("https://"):
            urls.append("http://" + url[8:])
        for u in urls:
            try:
                try:
                    r = self.fetch(u, headers=self.header(), timeout=10)
                except TypeError:
                    r = self.fetch(u, headers=self.header())
                text = r.text
                if text:
                    return text
            except Exception:
                continue
        return ""

    def _fix_pic(self, p):
        try:
            if not p:
                return ""
            p = p.strip()
            if p.startswith("//"):
                return "https:" + p
            if p.startswith("http"):
                return p
            return urljoin(self.HOST + "/", p)
        except Exception:
            return ""

    def _parse_items(self, html):
        out = []
        try:
            for m in re.finditer(
                    r'<a class="videopic"[^>]*href="/movie/index(\d+)\.html"'
                    r'[^>]*title="([^"]*)"(.*?)</a>',
                    html, re.S):
                vid, name, blk = m.group(1), m.group(2).strip(), m.group(3)
                img = re.search(r'data-original="([^"]*)"', blk) or re.search(r'<img[^>]*src="([^"]*)"', blk)
                note = re.search(r'<span class="note[^"]*">([^<]*)</span>', blk)
                score = re.search(r'<span class="score">([^<]*)</span>', blk)
                remarks = note.group(1).strip() if note else ""
                sc = score.group(1).strip() if score else ""
                if sc and remarks:
                    remarks = remarks + " " + sc
                elif sc:
                    remarks = "评分:" + sc
                out.append({
                    "vod_id": vid,
                    "vod_name": name or "未知",
                    "vod_pic": self._fix_pic(img.group(1)) if img else "",
                    "vod_remarks": remarks,
                })
        except Exception:
            pass
        return out

    def _pagecount(self, html, pg):
        try:
            m = re.search(r'<span class="num">\s*\d+/(\d+)\s*</span>', html)
            if m:
                return int(m.group(1))
        except Exception:
            pass
        return pg

    # ---------- TVBox 标准接口 ----------

    def homeContent(self, filter):
        result = {"class": [], "filters": {}}
        try:
            for tid, name in self.CATS:
                result["class"].append({"type_id": tid, "type_name": name})
        except Exception:
            pass
        return result

    def homeVideoContent(self):
        try:
            cached = self._cache_get("home", 600)
            if cached is not None:
                return cached
            html = self._req("/")
            result = {"list": self._parse_items(html)}
            if result["list"]:
                self._cache_set("home", result)
            return result
        except Exception:
            return {"list": []}

    def categoryContent(self, tid, pg, filter, extend):
        result = {"list": [], "page": 1, "pagecount": 1, "limit": 0, "total": 0}
        try:
            try:
                pg = int(pg)
            except (TypeError, ValueError):
                pg = 1
            if pg < 1:
                pg = 1
            key = "cat:%s:%d" % (tid, pg)
            cached = self._cache_get(key, 300)
            if cached is not None:
                return cached
            html = self._req("/search.php?searchtype=5&tid=%s&page=%d" % (tid, pg))
            if not html:
                return result
            lst = self._parse_items(html)
            pagecount = self._pagecount(html, pg)
            result = {
                "list": lst,
                "page": pg,
                "pagecount": pagecount,
                "limit": len(lst),
                "total": pagecount * max(len(lst), 1),
            }
            if lst:
                self._cache_set(key, result)
        except Exception:
            pass
        return result

    def _line_episodes(self, html, vid, line_no):
        """取一条线路的选集: 先看详情页内联, 没有则请求 playlist.php"""
        eps = []
        try:
            # 定位该线路面板区块
            starts = [m for m in re.finditer(
                r'data-playlist-name="[^"]*" data-playlist-line="(%d)"' % int(line_no), html)]
            if starts:
                s = starts[0].start()
                nxt = re.search(r'data-playlist-name="[^"]*" data-playlist-line="[0-9]+"', html[s + 50:])
                seg = html[s: s + 50 + nxt.start()] if nxt else html[s: s + 20000]
                for li in re.finditer(
                        r'<a[^>]*title="([^"]*)"[^>]*href="(/play/%s-[0-9]+-[0-9]+\.html)"' % vid, seg):
                    eps.append((li.group(2), li.group(1)))
            if not eps:
                frag = self._req("/playlist.php?id=%s&line=%s" % (vid, line_no))
                for li in re.finditer(
                        r'<a[^>]*title="([^"]*)"[^>]*href="(/play/%s-[0-9]+-[0-9]+\.html)"' % vid, frag):
                    eps.append((li.group(2), li.group(1)))
        except Exception:
            pass
        return eps

    def detailContent(self, ids):
        try:
            vid = str(ids[0]).replace("/movie/index", "").replace(".html", "")
            ckey = "detail:%s" % vid
            cached = self._cache_get(ckey, 900)
            if cached is not None:
                return cached
            html = self._req("/movie/index%s.html" % vid)
            if not html:
                return {"list": []}

            name, tname = "未知", ""
            m = re.search(r'<title>《([^》]+)》[^<]*-\s*([^<|]+?)\s*\|\s*袋鼠影视', html)
            if m:
                name, tname = m.group(1).strip(), m.group(2).strip()
            else:
                h1 = re.search(r"<h1[^>]*>([^<]+)</h1>", html)
                if h1:
                    name = h1.group(1).strip()

            pic = ""
            og = re.search(r'property="og:image" content="([^"]*)"', html)
            if og:
                pic = self._fix_pic(og.group(1))

            desc = ""
            md = re.search(r'<meta name="description" content="([^"]*)"', html)
            if md:
                desc = re.sub(r'^《[^》]*》是[^，]*，免费在线观看全集及最新播放线路。', "", md.group(1))

            remarks = ""
            mn = re.search(r'<span class="note textbg">([^<]*)</span>', html)
            if mn:
                remarks = mn.group(1).strip()

            # 年份/地区等 meta
            year, area = "", ""
            for li in re.finditer(r'<li data-video-meta="([^"]*)"><span class="text-muted">([^：<]*)：</span>(.*?)</li>', html, re.S):
                label, val = li.group(2).strip(), li.group(1).strip()
                if label == "上映" or "年份" in label:
                    year = val
                elif label == "地区":
                    area = val

            # 多线路选集
            names = []
            plays = []
            seen_lines = set()
            try:
                for lm in re.finditer(
                        r'data-playlist-name="([^"]*)" data-playlist-line="([0-9]+)"', html):
                    lname, lno = lm.group(1).strip(), lm.group(2)
                    if lno in seen_lines:
                        continue
                    seen_lines.add(lno)
                    eps = self._line_episodes(html, vid, lno)
                    if not eps:
                        continue
                    names.append(lname or ("线路%s" % (len(names) + 1)))
                    plays.append("#".join("%s$%s" % (n, p) for p, n in eps))
            except Exception:
                pass

            vod = {
                "vod_id": vid,
                "vod_name": name,
                "vod_pic": pic,
                "type_name": tname,
                "vod_year": year,
                "vod_area": area,
                "vod_remarks": remarks,
                "vod_actor": "",
                "vod_director": "",
                "vod_content": desc,
                "vod_play_from": "$$$".join(names) if names else "袋鼠影视",
                "vod_play_url": "$$$".join(plays) if plays else "",
            }
            result = {"list": [vod]}
            self._cache_set(ckey, result)
            return result
        except Exception:
            return {"list": []}

    def playerContent(self, flag, id, vipFlags):
        try:
            path = id
            if not path.startswith("/play/"):
                m = re.search(r'/play/[0-9]+-[0-9]+-[0-9]+\.html', str(id))
                path = m.group(0) if m else "/play/%s.html" % id
            ckey = "play:%s" % path
            cached = self._cache_get(ckey, 1800)
            if cached is not None:
                return cached
            html = self._req(path)
            m = re.search(r'var\s+now\s*=\s*["\']([^"\']+)["\']', html)
            play = m.group(1).strip() if m else ""
            if not play:
                m2 = re.search(r'(https?://[^"\'\s<>]+\.m3u8[^"\'\s<>]*)', html)
                play = m2.group(1) if m2 else ""
            if play:
                result = {
                    "parse": 0,
                    "playUrl": "",
                    "url": play,
                    "header": {"User-Agent": self.UA, "Referer": self.HOST + "/"},
                }
                self._cache_set(ckey, result)
                return result
            # 兜底: 交给网页嗅探
            return {"parse": 1, "playUrl": "", "url": self.HOST + path,
                    "header": self.header()}
        except Exception:
            return {"parse": 1, "playUrl": "", "url": id, "header": self.header()}

    def searchContent(self, key, quick):
        # 影视仓首页搜索调用双参签名
        return self.searchContentPage(key, quick, 1)

    def searchContentPage(self, key, quick, pg):
        # 影视仓翻页搜索调用三参签名
        result = {"list": [], "page": 1}
        try:
            try:
                pg = int(pg)
            except (TypeError, ValueError):
                pg = 1
            if pg < 1:
                pg = 1
            ckey = "s:%s:%d" % (key, pg)
            cached = self._cache_get(ckey, 180)
            if cached is not None:
                return cached
            html = self._req("/search.php?searchword=%s&searchtype=2&page=%d" % (quote(key), pg))
            if html:
                result = {"list": self._parse_items(html), "page": pg,
                          "pagecount": self._pagecount(html, pg), "limit": 20, "total": 20}
                if result["list"]:
                    self._cache_set(ckey, result)
        except Exception:
            pass
        return result
