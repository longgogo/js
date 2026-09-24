# -*- coding: utf-8 -*-
# 多多影视 (https://dduotv01.top) TVBox Python 爬虫源
# 按资料库 py.py 框架编写: 继承 base.spider.Spider
#
# 接口说明(均为 GET, 需带请求头):
#   首页:  /api.php/web/index/home
#   分类:  /api.php/web/filter/vod?type_name=电影&page=1&sort=hits  (支持 class/area/year/sort)
#   详情:  /api.php/web/vod/get_detail?vod_id=xxxx  (play_from/play_url 用 $$$ 分组)
#   搜索:  /api.php/web/search/index?wd=xx&page=1&limit=15
#   解码:  /api.php/web/decode/url (POST protobuf)
# 请求头: web-sign: ddtvf65f3a83d6d9ad6f  /  X-Client: 8f3d2a1c7b6e5d4c9a0b1f2e3d4c5b6a
# 解码请求为 protobuf: f1=加密token f2=线路from f3=时间戳(ms) f4=nonce f5=签名 f6=com.web.player f7=1
# 签名: sha256("finger={finger}&id={id}&nonce={nonce}&sk={sk}&time={ts}&v=1") 大写hex
#       finger/sk 为站点内嵌固定常量; 服务端解密播放地址后经 f3 返回直链

import hashlib
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

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
    class Spider(object):

        def fetch(self, url, headers=None, timeout=15, **kw):
            req = urllib.request.Request(url, headers=headers or {})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                resp = type("Resp", (), {})()
                resp.text = r.read().decode("utf-8", "replace")
                resp.status_code = getattr(r, "status", 200)
                return resp

        def post(self, url, data=None, headers=None, timeout=15, **kw):
            if isinstance(data, str):
                data = data.encode("utf-8")
            req = urllib.request.Request(url, data=data, headers=headers or {})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                resp = type("Resp", (), {})()
                resp.text = r.read().decode("utf-8", "replace")
                resp.status_code = getattr(r, "status", 200)
                return resp


class Spider(Spider):

    HOST = "https://dduotv01.top"
    UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
    _cache = {}
    _cache_time = {}

    # 站点内嵌签名常量(wasm 提取, 服务端校验)
    WEB_SIGN = "ddtvf65f3a83d6d9ad6f"
    X_CLIENT = "8f3d2a1c7b6e5d4c9a0b1f2e3d4c5b6a"
    FINGER = "WF-2c064bc5b3400788f31b848849bc3a60f835423ba2dfe69d7ea93974c216e4f2"
    SK = "WEB-50a8e9c84a1dc05669a692ded99a2dac46527229e607a7be15db88dbc59059d1"
    APP_ID = "com.web.player"

    CATS = [("电影", "电影"), ("剧集", "剧集"), ("动漫", "动漫"), ("综艺", "综艺")]

    SORTS = [("hits", "人气"), ("time", "最新"), ("score", "评分")]
    YEARS = [("2026", "2026"), ("2025", "2025"), ("2024", "2024"), ("2023", "2023"),
             ("2022", "2022"), ("2021", "2021")]
    AREAS = [("中国大陆", "中国大陆"), ("中国香港", "中国香港"), ("美国", "美国"),
             ("韩国", "韩国"), ("日本", "日本"), ("英国", "英国"), ("泰国", "泰国")]

    def init(self, extend=""):
        self.header = {
            "User-Agent": self.UA,
            "Referer": self.HOST + "/",
            "Accept": "application/json",
            "web-sign": self.WEB_SIGN,
            "X-Client": self.X_CLIENT,
        }
        self._cache = {}
        self._cache_time = {}

    def getName(self):
        return "多多影视"

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

    # ---------- 网络与协议工具 ----------

    def _http(self, url, data=None, pb=False):
        headers = dict(self.header)
        if pb:
            headers["Content-Type"] = "application/x-protobuf"
            headers["Accept"] = "application/x-protobuf"
        req = urllib.request.Request(url, data=data, method="POST" if data else "GET")
        for k, v in headers.items():
            req.add_header(k, v)
        # 10 秒超时: 影视仓 UI 超时较短, 长挂会被判定失败
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.read()

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

    def _api(self, path):
        try:
            return json.loads(self._http(self.HOST + path).decode("utf-8"))
        except Exception:
            return {}

    @staticmethod
    def _pb_varint(v):
        out = b""
        while True:
            x = v & 0x7F
            v >>= 7
            out += bytes([x | (0x80 if v else 0)])
            if not v:
                return out

    @classmethod
    def _pb_str(cls, num, s):
        b = s.encode("utf-8")
        return bytes([(num << 3) | 2]) + cls._pb_varint(len(b)) + b

    @classmethod
    def _pb_int(cls, num, v):
        return bytes([(num << 3) | 0]) + cls._pb_varint(v)

    def _decode_url(self, token, frm):
        """调站点解码接口, 返回播放直链(失败返回空串)"""
        try:
            ts = str(int(time.time() * 1000))
            # 部分运行时无 secrets 模块, 用 hashlib 生成 nonce
            nonce = hashlib.md5((ts + str(time.time())).encode("utf-8")).hexdigest()
            pre = "finger=%s&id=%s&nonce=%s&sk=%s&time=%s&v=1" % (
                self.FINGER, self.APP_ID, nonce, self.SK, ts)
            sign = hashlib.sha256(pre.encode("utf-8")).hexdigest().upper()
            payload = (self._pb_str(1, token) + self._pb_str(2, frm)
                       + self._pb_int(3, int(ts)) + self._pb_str(4, nonce)
                       + self._pb_str(5, sign) + self._pb_str(6, self.APP_ID)
                       + self._pb_int(7, 1))
            body = self._http(self.HOST + "/api.php/web/decode/url", data=payload, pb=True)
            # 解析响应 protobuf: f1=code(varint) f2=msg(str) f3=data(str)
            code, data = None, ""
            i = 0
            while i < len(body):
                tag = body[i]
                i += 1
                fnum, wt = tag >> 3, tag & 7
                if wt == 0:
                    v, sh = 0, 0
                    while True:
                        by = body[i]
                        i += 1
                        v |= (by & 0x7F) << sh
                        sh += 7
                        if not by & 0x80:
                            break
                    if fnum == 1:
                        code = v
                elif wt == 2:
                    ln, sh = 0, 0
                    while True:
                        by = body[i]
                        i += 1
                        ln |= (by & 0x7F) << sh
                        sh += 7
                        if not by & 0x80:
                            break
                    val = body[i:i + ln].decode("utf-8", "replace")
                    i += ln
                    if fnum == 3:
                        data = val
                else:
                    break
            if code == 1 and data:
                return data
        except Exception:
            pass
        return ""

    @staticmethod
    def _join(v):
        if isinstance(v, list):
            return ",".join(str(x) for x in v)
        return str(v) if v else ""

    @staticmethod
    def _strip_html(s):
        return re.sub(r"<[^>]+>", "", s or "").strip()

    def _vod_card(self, it):
        return {
            "vod_id": str(it.get("vod_id", "")),
            "vod_name": it.get("vod_name", ""),
            "vod_pic": it.get("vod_pic", ""),
            "vod_remarks": it.get("vod_remarks", ""),
        }

    # ---------- TVBox 标准接口 ----------

    def homeContent(self, filter):
        result = {"class": [], "filters": {}}
        for tid, name in self.CATS:
            result["class"].append({"type_id": tid, "type_name": name})
            result["filters"][tid] = [
                {"key": "sort", "name": "排序",
                 "value": [{"n": n, "v": v} for v, n in self.SORTS]},
                {"key": "year", "name": "年份",
                 "value": [{"n": n, "v": v} for v, n in self.YEARS]},
                {"key": "area", "name": "地区",
                 "value": [{"n": n, "v": v} for v, n in self.AREAS]},
            ]
        return result

    def homeVideoContent(self):
        cached = self._cache_get("home", 600)
        if cached is not None:
            return cached
        d = self._api("/api.php/web/index/home")
        out = []
        data = d.get("data") or {}
        for it in data.get("recommend") or []:
            out.append(self._vod_card(it))
        if not out:
            for cat in data.get("categories") or []:
                for it in (cat.get("videos") or [])[:6]:
                    out.append(self._vod_card(it))
        result = {"list": out}
        if out:
            self._cache_set("home", result)
        return result

    def categoryContent(self, tid, pg, filter, extend):
        try:
            pg = int(pg)
        except (TypeError, ValueError):
            pg = 1
        if pg < 1:
            pg = 1
        extend = extend or {}
        if not isinstance(extend, dict):
            try:
                extend = json.loads(extend)
            except Exception:
                extend = {}
        params = ["type_name=" + urllib.parse.quote(str(tid)),
                  "page=%d" % pg,
                  "sort=" + urllib.parse.quote(str(extend.get("sort") or "hits"))]
        if extend.get("year"):
            params.append("year=" + urllib.parse.quote(str(extend["year"])))
        if extend.get("area"):
            params.append("area=" + urllib.parse.quote(str(extend["area"])))
        if extend.get("class"):
            params.append("class=" + urllib.parse.quote(str(extend["class"])))
        key = "cat:" + "&".join(params)
        cached = self._cache_get(key, 300)
        if cached is not None:
            return cached
        d = self._api("/api.php/web/filter/vod?" + "&".join(params))
        lst = [self._vod_card(it) for it in (d.get("data") or [])]
        try:
            pagecount = max(int(d.get("pageCount") or 1), 1)
        except (TypeError, ValueError):
            pagecount = pg if lst else 1
        result = {
            "list": lst,
            "page": pg,
            "pagecount": pagecount,
            "limit": len(lst),
            "total": int(d.get("total") or len(lst)),
        }
        if lst:
            self._cache_set(key, result)
        return result

    def detailContent(self, ids):
        vid = ids[0]
        ckey = "detail:%s" % vid
        cached = self._cache_get(ckey, 900)
        if cached is not None:
            return cached
        d = self._api("/api.php/web/vod/get_detail?vod_id=" + urllib.parse.quote(str(vid)))
        arr = d.get("data") or []
        if not arr:
            return {"list": []}
        v = arr[0]
        show_map = {}
        for p in d.get("vodplayer") or []:
            if isinstance(p, dict) and p.get("from"):
                show_map[p["from"]] = p.get("show") or p["from"]

        froms = [x.strip() for x in (v.get("vod_play_from") or "").split("$$$") if x.strip()]
        groups = (v.get("vod_play_url") or "").split("$$$")
        play_from_parts = []
        play_url_parts = []
        for i, group in enumerate(groups):
            if not group.strip():
                continue
            frm = froms[i] if i < len(froms) else ("线路%d" % (i + 1))
            play_from_parts.append(show_map.get(frm, frm))
            eps = []
            for item in group.split("#"):
                item = item.strip()
                if not item or "$" not in item:
                    continue
                name, token = item.split("$", 1)
                eps.append("%s$%s@%s" % (name, frm, token))
            if eps:
                play_url_parts.append("#".join(eps))
        vod = {
            "vod_id": str(v.get("vod_id", vid)),
            "vod_name": v.get("vod_name", ""),
            "vod_pic": v.get("vod_pic", ""),
            "type_name": self._join(v.get("vod_class")),
            "vod_year": self._join(v.get("vod_year")),
            "vod_area": self._join(v.get("vod_area")),
            "vod_lang": self._join(v.get("vod_lang")),
            "vod_remarks": self._join(v.get("vod_remarks")),
            "vod_actor": self._join(v.get("vod_actor")),
            "vod_director": self._join(v.get("vod_director")),
            "vod_content": self._strip_html(v.get("vod_content")),
            "vod_play_from": "$$$".join(play_from_parts),
            "vod_play_url": "$$$".join(play_url_parts),
        }
        result = {"list": [vod]}
        self._cache_set(ckey, result)
        return result

    def playerContent(self, flag, id, vipFlags):
        ckey = "play:%s" % id
        cached = self._cache_get(ckey, 900)
        if cached is not None:
            return cached
        play = ""
        try:
            frm, token = id.split("@", 1)
            play = self._decode_url(token, frm)
        except Exception:
            play = ""
        result = {
            "parse": 0,
            "playUrl": "",
            "url": play,
            "header": {"User-Agent": self.UA, "Referer": self.HOST + "/"},
        }
        if play:
            self._cache_set(ckey, result)
        return result

    def searchContent(self, key, quick):
        return self.searchContentPage(key, quick, 1)

    def searchContentPage(self, key, quick, pg):
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
        d = self._api("/api.php/web/search/index?wd=" + urllib.parse.quote(key)
                      + "&page=%d&limit=15" % pg)
        lst = [self._vod_card(it) for it in (d.get("data") or [])]
        result = {"list": lst, "page": pg, "pagecount": pg + 1 if len(lst) >= 15 else pg,
                  "limit": len(lst), "total": len(lst)}
        if lst:
            self._cache_set(ckey, result)
        return result
