# coding=utf-8
# !/usr/bin/python
# HDmoli (hdmoli.me) TVBox DRPY source
# by WorkBuddy
import sys
import os
sys.path.append("..")
import re
import json
import time
import hashlib
import urllib.parse
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad
from base64 import b64decode
from base.spider import Spider


class Spider(Spider):

    HOST = "https://www.hdmoli.me"
    # 播放地址解密盐(来自站点播放器JS)
    SALT = "RY7e48naFXPsLJC"
    # 智能播放解析接口
    SMART_API = "https://hd.ticktockwow.com/smartplay-cache/api/webvideo_ty.php"

    NAME = "HDmoli"

    UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

    CLASSES = [
        {"type_name": "电影", "type_id": "1"},
        {"type_name": "剧集", "type_id": "2"},
        {"type_name": "动画", "type_id": "4"},
    ]

    AREAS = ["大陆", "香港", "台湾", "美国", "英国", "日本", "韩国", "法国", "德国",
             "意大利", "西班牙", "俄罗斯", "丹麦", "加拿大", "澳大利亚", "爱尔兰",
             "瑞典", "芬兰", "比利时", "希腊", "土耳其", "巴西", "印度", "泰国",
             "新西兰", "智利", "其它"]

    CLS = ["动作", "喜剧", "爱情", "科幻", "奇幻", "剧情", "悬疑", "惊悚", "恐怖",
           "犯罪", "冒险", "战争", "历史", "古装", "武侠", "家庭", "儿童", "传记",
           "音乐", "歌舞", "运动", "西部", "灾难", "纪录片", "短片", "真人秀"]

    YEARS = ["2026", "2025", "2024", "2023", "2022", "2021", "2020",
             "2019", "2018", "2017", "2016", "2015"]

    def getName(self):
        return self.NAME

    def init(self, extend=""):
        pass

    def isVideoFormat(self, url):
        pass

    def manualVideoCheck(self):
        pass

    def action(self, action):
        pass

    def destroy(self):
        pass

    def header(self):
        return {
            "User-Agent": self.UA,
            "Referer": self.HOST + "/",
        }

    # ---------------- 首页 ----------------

    def homeContent(self, filter):
        result = {"class": self.CLASSES}
        if filter:
            filters = {}
            value_area = [{"n": v, "v": v} for v in self.AREAS]
            value_cls = [{"n": v, "v": v} for v in self.CLS]
            value_year = [{"n": v, "v": v} for v in self.YEARS]
            for c in self.CLASSES:
                tid = c["type_id"]
                filters[tid] = [
                    {"key": "class", "name": "类型", "value": value_cls},
                    {"key": "area", "name": "地区", "value": value_area},
                    {"key": "year", "name": "年份", "value": value_year},
                ]
            result["filters"] = filters
        return result

    def homeVideoContent(self):
        html = self.fetch(self.HOST + "/", headers=self.header()).text
        return {"list": self._cards(html)}

    # ---------------- 分类 ----------------

    def _show_url(self, tid, extend, pg):
        extend = extend or {}
        area = extend.get("area", "") or ""
        cls = extend.get("class", "") or ""
        year = extend.get("year", "") or ""
        pg_seg = "" if str(pg) in ("", "1", None) else str(pg)
        segs = [str(tid), area, "", cls, "", "", "", "", pg_seg, "", year]
        return self.HOST + "/show/" + "-".join(segs) + ".html"

    def categoryContent(self, tid, pg, filter, extend):
        pg = int(pg) if str(pg).isdigit() else 1
        url = self._show_url(tid, extend, pg)
        html = self.fetch(url, headers=self.header()).text
        result = {}
        result["list"] = self._cards(html)
        result["page"] = pg
        result["pagecount"] = 9999
        result["limit"] = 90
        result["total"] = 999999
        return result

    # ---------------- 详情 ----------------

    def detailContent(self, ids):
        vid = ids[0]
        html = self.fetch("{}/movie/index{}.html".format(self.HOST, vid),
                          headers=self.header()).text

        vod = {"vod_id": vid}
        m = re.search(r'<h1 class="title[^"]*">(.*?)</h1>', html, re.S)
        if m:
            name = re.sub(r'<font[^>]*>.*?</font>', '', m.group(1), flags=re.S).strip()
            vod["vod_name"] = name
            rm = re.search(r'<font[^>]*>([^<]+)</font>', m.group(1))
            if rm:
                vod["vod_remarks"] = rm.group(1).strip()
        sm = re.search(r'<span class="branch">([^<]+)</span>', html)
        if sm:
            vod["vod_score"] = sm.group(1).strip()

        def data_val(label):
            mm = re.search(label + r'：</span><a[^>]*>([^<]+)</a>', html)
            return mm.group(1).strip() if mm else ''

        vod["type_name"] = data_val(r'分类')
        vod["vod_area"] = data_val(r'地区')
        vod["vod_lang"] = data_val(r'语言')
        vod["vod_year"] = data_val(r'年份')

        am = re.search(r'演员：</span>(.*?)</p>', html, re.S)
        if am:
            vod["vod_actor"] = " ".join(
                re.findall(r'>([^<>]+)</a>', am.group(1))).strip()
        dm = re.search(r'导演：</span>(.*?)</p>', html, re.S)
        if dm:
            vod["vod_director"] = " ".join(
                re.findall(r'>([^<>]+)</a>', dm.group(1))).strip() or "未知"

        cm = re.search(r'<span class="detail[^"]*">(.*?)</span>', html, re.S)
        if cm:
            vod["vod_content"] = re.sub(r'<[^>]+>', '', cm.group(1)).strip()
        else:
            cm = re.search(r'<div class="text-content[^"]*"[^>]*>(.*?)</div>', html, re.S)
            if cm:
                vod["vod_content"] = re.sub(r'<[^>]+>', '', cm.group(1)).strip()

        # 线路与集数
        tabs = re.findall(r'href="#playlist(\d+)"[^>]*>([^<]+)</a>', html)
        play_from = []
        play_list = []
        for idx, tab_name in tabs:
            if "网盘" in tab_name:
                continue
            seg = re.search(
                r'<div id="playlist' + idx + r'"(.*?)</div>\s*(?:<div id="playlist|<!--)',
                html, re.S)
            if not seg:
                seg = re.search(r'<div id="playlist' + idx + r'"(.*)', html, re.S)
            body = seg.group(1)
            eps = re.findall(r'href="(/play/\d+-\d+-\d+\.html)"[^>]*>([^<]+)</a>', body)
            if not eps:
                continue
            play_from.append(tab_name.strip())
            play_list.append("#".join(
                "{}${}".format(ep_name.strip(), ep_path) for ep_path, ep_name in eps))

        vod["vod_play_from"] = "$$$".join(play_from)
        vod["vod_play_url"] = "$$$".join(play_list)
        return {"list": [vod]}

    # ---------------- 搜索 ----------------

    def searchContent(self, key, quick, pg="1"):
        url = "{}/search/{}-------------.html".format(
            self.HOST, urllib.parse.quote(key))
        html = self.fetch(url, headers=self.header()).text
        return {"list": self._cards(html), "page": 1}

    # ---------------- 播放 ----------------

    def _aes_decrypt(self, blob, ts):
        """execB 还原: md5(ts+salt) 后16位为key, 前16位为iv, AES-128-CBC/Pkcs7"""
        md5hex = hashlib.md5((ts + self.SALT).encode("utf-8")).hexdigest()
        key = md5hex[16:].encode("utf-8")
        iv = md5hex[:16].encode("utf-8")
        cipher = AES.new(key, AES.MODE_CBC, iv)
        return unpad(cipher.decrypt(b64decode(blob)), AES.block_size).decode("utf-8")

    def playerContent(self, flag, id, vipFlags):
        result = {"parse": 0, "playUrl": "", "url": ""}
        try:
            play_path = id if id.startswith("/") else "/" + id
            html = self.fetch(self.HOST + play_path, headers=self.header()).text
            pm = re.search(r'var player_aaaa=(\{.*?\})\s*</script>', html, re.S)
            if not pm:
                return result
            pa = json.loads(pm.group(1))
            hexurl = pa.get("url", "")

            # artplayer 播放器页
            iframe = self.fetch(
                "{}/static/player/artplayer/?url={}".format(self.HOST, hexurl),
                headers=self.header()).text

            tsm = re.search(r'const timestamp\s*=\s*"(\d+)"', iframe)
            ts = tsm.group(1) if tsm else str(int(time.time()))

            real = ""
            # 路径1: 页面内置 qualities 直接解密
            qm = re.search(r'const qualities\s*=\s*(\[.*?\]);', iframe, re.S)
            if qm:
                try:
                    qlist = json.loads(qm.group(1))
                    if qlist and qlist[0].get("url"):
                        real = self._aes_decrypt(qlist[0]["url"], ts)
                except Exception:
                    pass

            # 路径2: 智能播放接口
            if not real:
                vm = re.search(r'const playPageUrl\s*=\s*"([^"]*)"', iframe)
                cm = re.search(r'const secretKeySeed\s*=\s*"([^"]*)"', iframe)
                vkey = vm.group(1) if vm else ""
                code = cm.group(1) if cm else ""
                t = str(int(time.time()))
                body = json.dumps({
                    "vkey": vkey,
                    "code": code,
                    "t": int(t),
                    "signature": hashlib.md5(t.encode("utf-8")).hexdigest(),
                })
                headers = {
                    "User-Agent": self.UA,
                    "Content-Type": "application/json",
                    "Origin": self.HOST,
                    "Referer": self.HOST + "/",
                }
                resp = self.post(self.SMART_API, body, headers=headers)
                data = resp.json()
                if str(data.get("code")) == "200" and data.get("url"):
                    real = self._aes_decrypt(data["url"], ts)

            result["url"] = real
            result["header"] = {
                "User-Agent": self.UA,
                "Referer": self.HOST + "/",
            }
        except Exception as e:
            result["url"] = ""
        return result

    # ---------------- 解析辅助 ----------------

    def _cards(self, html):
        videos = []
        # 统一按缩略图锚点切块, 兼容首页/分类/搜索三种卡片结构
        parts = html.split('<a class="myui-vodlist__thumb')
        for part in parts[1:]:
            m = re.search(
                r'href="(/movie/index(\d+)\.html)"[^>]*title="([^"]*)"[^>]*data-original="([^"]*)"',
                part)
            if not m:
                m = re.search(
                    r'href="(/movie/index(\d+)\.html)"[^>]*data-original="([^"]*)"[^>]*title="([^"]*)"',
                    part)
                if not m:
                    continue
                vid, name, pic = m.group(2), m.group(4), m.group(3)
            else:
                vid, name, pic = m.group(2), m.group(3), m.group(4)
            remark = ""
            rm = re.search(r'pic-text[^>]*>([^<]+)', part)
            if rm:
                remark = rm.group(1).strip().replace("&nbsp;", " ")
            videos.append({
                "vod_id": vid,
                "vod_name": name.strip(),
                "vod_pic": pic.replace("&amp;", "&"),
                "vod_remarks": remark,
            })
        return videos
