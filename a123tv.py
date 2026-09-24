# -*- coding: utf-8 -*-
# A123TV (https://a123tv.com) TVBox Python 爬虫源
# 按资料库 py.py 框架编写: 继承 base.spider.Spider
# 结构要点:
#   首页/分类/搜索列表条目: <a class="w4-item" href="/v/xxx.html"> + <img data-src>(懒加载) + <div class="t" title> + <div class="i">类型/年份
#   分类: /t/{tid}.html  分页: /t/{tid}/p{pg}.html
#   详情: 线路 <a class="w4-line-item" href title="线路XXX">; 选集 <a href title="第XX集">
#   播放: 子页 <div class="w4-player" data-src="m3u8直链">
#   搜索: /s/{urlencode(关键词)}.html

import re
from urllib.parse import quote

from base.spider import Spider


class Spider(Spider):

    HOST = "https://a123tv.com"
    UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

    # 首页导航完整分类映射(实测提取)
    CATS = [
        ("10", "电影"),
        ("1001", "动作片"), ("1002", "喜剧片"), ("1003", "爱情片"),
        ("1004", "科幻片"), ("1005", "恐怖片"), ("1006", "剧情片"),
        ("1007", "战争片"), ("1008", "纪录片"), ("1010", "动漫电影"),
        ("1011", "奇幻片"), ("1013", "动画片"), ("1014", "犯罪片"),
        ("1016", "悬疑片"), ("1019", "邵氏电影"), ("1022", "歌舞片"),
        ("1024", "家庭片"), ("1025", "古装片"), ("1026", "历史片"),
        ("1027", "4K电影"),
        ("11", "连续剧"),
        ("1101", "国产剧"), ("1102", "香港剧"), ("1103", "韩国剧"),
        ("1104", "欧美剧"), ("1105", "台湾剧"), ("1106", "日本剧"),
        ("1107", "海外剧"), ("1108", "泰国剧"), ("1110", "港台剧"),
        ("1111", "日韩剧"),
        ("12", "综艺"),
        ("1201", "内地综艺"), ("1202", "港台综艺"), ("1203", "日韩综艺"),
        ("1204", "欧美综艺"), ("1205", "国外综艺"),
        ("13", "动漫"),
        ("1301", "国产动漫"), ("1302", "日韩动漫"), ("1303", "欧美动漫"),
        ("1305", "海外动漫"), ("1307", "里番"),
        ("15", "福利"),
        ("1550", "其它情色片"), ("1551", "韩国情色片"), ("1552", "日本情色片"),
        ("1553", "香港情色片"), ("1554", "台湾情色片"), ("1555", "大陆情色片"),
        ("1556", "美国情色片"), ("1557", "欧洲情色片"), ("1558", "印度情色片"),
        ("1559", "东南亚情色片"),
    ]

    def init(self, extend=""):
        self.header = {"User-Agent": self.UA, "Referer": self.HOST + "/"}

    def getName(self):
        return "A123TV"

    def isVideoFormat(self, url):
        return True

    def manualVideoCheck(self):
        return False

    # ---------- 内部工具 ----------

    def _get(self, path):
        r = self.fetch(self.HOST + path, headers=self.header)
        return r.text

    def _get_url(self, url):
        r = self.fetch(url, headers=self.header)
        return r.text

    def _fix_pic(self, p):
        if not p:
            return ""
        if p.startswith("//"):
            return "https:" + p
        if p.startswith("http"):
            return p
        return self.HOST + p

    def _parse_items(self, html):
        out = []
        for m in re.finditer(
                r'<a class="w4-item"[^>]*href="(/v/[^"]+\.html)"(.*?)</a>',
                html, re.S):
            path, blk = m.group(1), m.group(2)
            img = re.search(r'<img[^>]*data-src="([^"]*)"', blk)
            alt = re.search(r'<img[^>]*alt="([^"]*)"', blk)
            t = re.search(r'<div class="t"[^>]*title="([^"]*)"', blk)
            info = re.search(r'<div class="i">([^<]*)</div>', blk)
            name = (t.group(1) if t else "") or (alt.group(1) if alt else "") or "未知"
            pic = self._fix_pic(img.group(1)) if img else ""
            remarks = info.group(1).strip() if info else ""
            out.append({
                "vod_id": path,
                "vod_name": name,
                "vod_pic": pic,
                "vod_remarks": remarks,
            })
        return out

    # ---------- TVBox 标准接口 ----------

    def homeContent(self, filter):
        result = {"class": [], "filters": {}}
        for tid, name in self.CATS:
            result["class"].append({"type_id": tid, "type_name": name})
        return result

    def homeVideoContent(self):
        html = self._get("/")
        return {"list": self._parse_items(html)}

    def categoryContent(self, tid, pg, filter, extend):
        try:
            pg = int(pg)
        except (TypeError, ValueError):
            pg = 1
        if pg < 1:
            pg = 1
        path = "/t/%s.html" % tid if pg <= 1 else "/t/%s/p%d.html" % (tid, pg)
        html = self._get(path)
        lst = self._parse_items(html)
        pages = [int(x) for x in re.findall(r"/t/%s/p(\d+)\.html" % tid, html)]
        if pages:
            pagecount = max(max(pages), pg)
        elif "下一页" in html:
            pagecount = pg + 1
        else:
            pagecount = pg
        return {
            "list": lst,
            "page": pg,
            "pagecount": pagecount,
            "limit": len(lst),
            "total": pagecount * max(len(lst), 1),
        }

    def detailContent(self, ids):
        path = ids[0]
        if not path.startswith("/"):
            path = "/" + path
        html = self._get(path)

        title = re.search(r"<title>《([^》]*)》\s*-\s*([^<-]*)\s*-\s*(\d{4})年", html)
        h1 = re.search(r"<h1[^>]*>([^<]*)</h1>", html)
        name = title.group(1) if title else (h1.group(1) if h1 else "未知")
        tname = title.group(2).strip() if title else ""
        year = title.group(3) if title else ""

        pic = ""
        og = re.search(r'property="og:image" content="([^"]*)"', html)
        if og:
            pic = self._fix_pic(og.group(1))

        desc = re.search(r'<meta name="description" content="([^"]*)"', html)
        content = desc.group(1) if desc else ""

        # 优先选集(连续剧), 否则线路(电影)
        eps = []
        seen = set()
        for p, n in re.findall(
                r'<a[^>]*href="(/v/[^"]+\.html)"[^>]*title="(第[^"]*集)"', html):
            if p not in seen:
                seen.add(p)
                eps.append((p, n))
        play_url = "#".join("%s$%s%s" % (n, self.HOST, p) for p, n in eps)

        if not play_url:
            lines = []
            seen = set()
            for p, n in re.findall(
                    r'<a[^>]*href="(/v/[^"]+\.html)"[^>]*title="(线路[^"]*)"', html):
                if p not in seen:
                    seen.add(p)
                    lines.append((p, n))
            play_url = "#".join("%s$%s%s" % (n, self.HOST, p) for p, n in lines)

        vod = {
            "vod_id": path,
            "vod_name": name,
            "vod_pic": pic,
            "type_name": tname,
            "vod_year": year,
            "vod_area": "",
            "vod_actor": "",
            "vod_director": "",
            "vod_content": content,
            "vod_play_from": "A123TV",
            "vod_play_url": play_url,
        }
        return {"list": [vod]}

    def playerContent(self, flag, id, vipFlags):
        url = id
        if not url.startswith("http"):
            url = self.HOST + url
        html = self._get_url(url)
        m = re.search(r'class="w4-player"[^>]*data-src="([^"]*)"', html)
        play = m.group(1) if m else ""
        if play.startswith("//"):
            play = "https:" + play
        return {
            "parse": 0,
            "playUrl": "",
            "url": play,
            "header": {"User-Agent": self.UA, "Referer": self.HOST + "/"},
        }

    def searchContent(self, key, quick):
        return self.searchContentPage(key, quick, 1)

    def searchContentPage(self, key, quick, pg):
        try:
            pg = int(pg)
        except (TypeError, ValueError):
            pg = 1
        if pg > 1:
            return {"list": [], "page": pg, "pagecount": 1, "limit": 0, "total": 0}
        html = self._get("/s/" + quote(key) + ".html")
        lst = self._parse_items(html)
        return {"list": lst, "page": 1, "pagecount": 1, "limit": len(lst),
                "total": len(lst)}
