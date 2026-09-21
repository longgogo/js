# coding=utf-8
# !/usr/bin/python
# PPnix (www.ppnix.com) DRPY Python spider for TVBox
# 站点结构（2026-09-21 实测）:
#   列表/筛选: /movie/{类型}-{地区}-{年份}-{页}-.html  /tv/...   页码从 0 起(第1页留空或0)
#   详情:      /movie/{id}.html  /tv/{id}.html  内联脚本: infoid/m3u8=[...]/classid
#   播放:      /info/m3u8/{infoid}/{集}.m3u8  (电影集名为 1080P，剧集为 1..N)
#   搜索:      /search/{关键词}-{页}-.html    页码从 0 起(第1页留空)
#   m3u8 为 VOD，AES-128 key 相对路径 ../key，分片在 ipfs.ppnix.com，无 Referer 防盗链
import sys
import os
import re
import json
import time
import gzip
import ssl
import urllib.request
import urllib.parse

sys.path.append("..")

try:
    from base.spider import Spider as _BaseSpider
except Exception:
    _BaseSpider = object


class Spider(_BaseSpider):

    def getName(self):
        return "PPnix"

    def init(self, extend=""):
        self.host = "https://www.ppnix.com"
        self.timeout = 40
        try:
            self.extend = json.loads(extend) if extend else {}
        except Exception:
            self.extend = {}
        if isinstance(self.extend, dict) and self.extend.get("host"):
            self.host = self.extend["host"].rstrip("/")
        self.ctx = ssl.create_default_context()
        self.ctx.check_hostname = False
        self.ctx.verify_mode = ssl.CERT_NONE
        pass

    def isVideoFormat(self, url):
        pass

    def manualVideoCheck(self):
        pass

    def action(self, action):
        pass

    def destroy(self):
        pass

    UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"

    # ---------- 网络层 ----------
    def _get(self, url, retry=2):
        last = None
        for _ in range(retry + 1):
            try:
                req = urllib.request.Request(url, headers={
                    "User-Agent": self.UA,
                    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                    "Accept-Encoding": "gzip",
                })
                r = urllib.request.urlopen(req, timeout=self.timeout, context=self.ctx)
                data = r.read()
                if r.headers.get("Content-Encoding") == "gzip" or data[:2] == b"\x1f\x8b":
                    data = gzip.decompress(data)
                return data.decode("utf-8", "ignore")
            except Exception as e:
                last = e
                time.sleep(1)
        raise RuntimeError("fetch fail: %s (%s)" % (url, last))

    # ---------- 筛选数据（站点页面实测） ----------
    MOVIE_GENRES = ["Drama", "Thriller", "Comedy", "Action", "Romance", "Crime", "Adventure",
                    "Horror", "Mystery", "Fantasy", "Sci-Fi", "Family", "Animation", "Biography",
                    "History", "War", "Music", "Sport", "Musical", "Documentary", "Western",
                    "Short", "Film-Noir", "Talk-Show", "News"]
    TV_GENRES = ["Drama", "Thriller", "Mystery", "Crime", "Action", "Romance", "Comedy",
                 "Fantasy", "Sci-Fi", "Adventure", "Horror", "History", "Animation", "War",
                 "Family", "Biography", "Western", "Sport", "Short", "Reality-TV", "Musical",
                 "Music", "Documentary"]
    MOVIE_AREAS = ["United States", "United Kingdom", "Japan", "France", "China", "Hong Kong",
                   "Canada", "South Korea", "Germany", "Italy", "Australia", "Spain", "Taiwan",
                   "India", "Belgium", "Thailand", "Sweden", "Ireland", "Mexico", "Denmark",
                   "Russia", "Switzerland", "Netherlands", "New Zealand", "Singapore", "Hungary",
                   "Norway", "Finland", "South Africa", "Poland", "Brazil", "Bulgaria", "Austria",
                   "Luxembourg", "Czech Republic", "West Germany", "Argentina", "Turkey",
                   "Romania", "United Arab Emirates", "Malaysia", "Philippines", "Indonesia",
                   "Iceland", "Portugal", "Serbia", "Morocco", "Vietnam", "Greece", "Colombia",
                   "Qatar", "Jordan", "Iran", "Croatia", "Soviet Union", "Malta", "Israel",
                   "Chile", "Cambodia", "Ukraine", "Latvia", "Slovakia", "Estonia", "Cyprus",
                   "Slovenia", "Puerto Rico", "Bermuda", "Saudi Arabia", "North Macedonia",
                   "Nepal", "Monaco", "Lithuania", "Czechoslovakia", "Belarus", "Bahamas",
                   "Yugoslavia", "Venezuela", "Uruguay", "Tunisia", "Peru",
                   "Occupied Palestinian Territory", "Macao", "Lebanon", "Korea", "Kenya",
                   "Kazakhstan", "Jamaica", "Isle of Man", "Iraq", "Dominican Republic", "Cuba",
                   "Botswana", "Algeria", "Zambia", "Vanuatu", "Serbia and Montenegro",
                   "Paraguay", "Panama", "Pakistan", "Nigeria", "Liechtenstein", "Liberia",
                   "Kuwait", "Guadeloupe", "Gambia", "Federal Republic of Yugoslavia", "Egypt",
                   "Costa Rica", "Cayman Islands", "British Virgin Islands", "Bolivia", "Bhutan",
                   "Bahrain", "Armenia", "Afghanistan"]
    TV_AREAS = ["United States", "China", "South Korea", "United Kingdom", "Japan", "Taiwan",
                "Hong Kong", "France", "Thailand", "Canada", "Ireland", "Australia", "Poland",
                "Korea", "Hungary", "Colombia", "Spain", "South Africa", "Singapore", "Mexico",
                "Denmark", "Argentina"]

    def _years(self):
        # 站点年份筛选 1916~2026（/movie/--YYYY--.html 实测存在）
        return [{"n": str(y), "v": str(y)} for y in range(2026, 1915, -1)]

    def _genres(self, names):
        return [{"n": n, "v": n.replace("-", " ")} for n in names]

    def _areas(self, names):
        return [{"n": n, "v": n} for n in names]

    # ---------- 卡片解析 ----------
    def _cards(self, html):
        videos = []
        for m in re.finditer(
                r'<li><a href="/(movie|tv)/(\d+)\.html" class="thumbnail"[^>]*>'
                r'<img[^>]*?src="([^"]+)"[^>]*?class="thumb" alt="([^"]*)"',
                html):
            cls, vid, pic, alt = m.groups()
            block = html[m.start():m.start() + 1200]
            name = alt
            nm = re.search(r'<h2><a href="/(?:movie|tv)/\d+\.html"[^>]*title="([^"]*)"', block)
            if nm and nm.group(1):
                name = nm.group(1)
            remark = ""
            rm = re.search(r'class="orange">([^<]*)</span>', block)
            if rm:
                remark = rm.group(1).strip()
            nm2 = re.search(r'<div class="note"><span>([^<]+)</span>', block)
            if nm2 and nm2.group(1).strip():
                remark = nm2.group(1).strip()
            videos.append({
                "vod_id": "%s/%s" % (cls, vid),
                "vod_name": name.strip(),
                "vod_pic": pic.replace("&amp;", "&"),
                "vod_remarks": remark,
            })
        return videos

    def _pagecount(self, html):
        m = re.search(r'<a href="/(?:movie|tv|search)/[^"]*?-(\d+)-\.html">Last</a>', html)
        if m:
            return int(m.group(1)) + 1
        return 9999

    # ---------- DRPY 接口 ----------
    def homeContent(self, filter):
        result = {}
        classes = [
            {"type_name": "电影", "type_id": "movie"},
            {"type_name": "剧集", "type_id": "tv"},
        ]
        result["class"] = classes
        if filter:
            filters = {
                "movie": [
                    {"key": "class", "name": "类型", "value": self._genres(self.MOVIE_GENRES)},
                    {"key": "area", "name": "地区", "value": self._areas(self.MOVIE_AREAS)},
                    {"key": "year", "name": "年份", "value": self._years()},
                ],
                "tv": [
                    {"key": "class", "name": "类型", "value": self._genres(self.TV_GENRES)},
                    {"key": "area", "name": "地区", "value": self._areas(self.TV_AREAS)},
                    {"key": "year", "name": "年份", "value": self._years()},
                ],
            }
            result["filters"] = filters
        return result

    def homeVideoContent(self):
        html = self._get(self.host + "/")
        return {"list": self._cards(html)}

    def categoryContent(self, tid, pg, filter, extend):
        extend = extend or {}
        try:
            pg = int(pg)
        except Exception:
            pg = 1
        g = extend.get("class", "")
        a = extend.get("area", "")
        y = extend.get("year", "")
        g = g.replace("-", " ") if g else ""
        path = "/%s/%s-%s-%s-%s-.html" % (
            tid,
            urllib.parse.quote(g) if g else "",
            urllib.parse.quote(a) if a else "",
            urllib.parse.quote(y) if y else "",
            pg - 1,
        )
        html = self._get(self.host + path)
        result = {
            "list": self._cards(html),
            "page": pg,
            "pagecount": self._pagecount(html),
            "limit": 24,
            "total": 999999,
        }
        return result

    def detailContent(self, ids):
        did = ids[0]  # 形如 movie/8458
        html = self._get("%s/%s.html" % (self.host, did))
        # 内联变量
        infoid = "0"
        m = re.search(r"infoid=(\d+)", html)
        if m:
            infoid = m.group(1)
        eps = []
        m = re.search(r"m3u8=(\[[^\]]*\])", html)
        if m:
            eps = re.findall(r"'([^']*)'", m.group(1))
        # 头部信息
        vod_name, vod_year = "", ""
        m = re.search(r'<h1 class="product-title">(.*?)</h1>', html, re.S)
        if m:
            seg = m.group(1)
            t = re.split(r"<span", seg)[0]
            vod_name = re.sub(r"<[^>]*>", "", t).strip()
            ym = re.search(r"\((\d{4})\)", seg)
            if ym:
                vod_year = ym.group(1)
        vod_pic = ""
        m = re.search(r'<header class="product-header"><img src="([^"]+)"', html)
        if m:
            vod_pic = m.group(1)
        vod_area = self._excerpt(html, "Countries")
        vod_type = self._excerpt(html, "Genres")
        vod_actor = self._excerpt(html, "Casts")
        vod_director = self._excerpt(html, "Directors")
        vod_remarks = self._excerpt(html, "Aka")
        vod_content = self._excerpt(html, "Summary")
        rate = ""
        m = re.search(r'<h1 class="product-title">.*?<span class="rate">([^<]*)</span>', html, re.S)
        if m:
            rate = m.group(1).strip()
        play_urls = ["%s$%s/info/m3u8/%s/%s.m3u8" % (
            e, self.host, infoid, urllib.parse.quote(e)) for e in eps]
        video = {
            "vod_id": did,
            "vod_name": vod_name,
            "vod_pic": vod_pic,
            "type_name": vod_type,
            "vod_year": vod_year,
            "vod_area": vod_area,
            "vod_remarks": (vod_remarks + (" 评分" + rate if rate else "")) if vod_remarks else ("评分" + rate if rate else ""),
            "vod_actor": vod_actor,
            "vod_director": vod_director,
            "vod_content": vod_content,
            "vod_play_from": "PPnix",
            "vod_play_url": "#".join(play_urls),
        }
        return {"list": [video]}

    def _excerpt(self, html, label):
        m = re.search(r'<div class="product-excerpt">' + label +
                      r'：?<span>(.*?)</span></div>', html, re.S)
        if not m:
            return ""
        seg = m.group(1)
        # 多值以 / 分隔
        parts = [re.sub(r"<[^>]*>", "", p).strip() for p in seg.split(" / ")]
        return " / ".join(p for p in parts if p)

    def searchContent(self, key, quick, pg=1):
        try:
            pg = int(pg)
        except Exception:
            pg = 1
        wd = urllib.parse.quote(key.replace("-", " "))
        html = self._get("%s/search/%s-%s-.html" % (self.host, wd, pg - 1))
        result = {"list": self._cards(html), "page": pg}
        return result

    def playerContent(self, flag, id, vipFlags):
        url = id
        result = {}
        result["parse"] = 0
        result["playUrl"] = ""
        result["url"] = url
        result["header"] = json.dumps({"User-Agent": self.UA})
        return result

    def localProxy(self, param):
        pass
