# coding=utf-8
"""
KStore 直链网盘 —— TVBox Python 蜘蛛（DRPY / py 源）
=================================================
站点：https://kstore.cc  （API 基址 https://api.kstore.cc/api/v2）
来源：按用户给定的 kstore.cc/file?filePath=ys/&fileType=0 目录做成可播放源
原理：KStore 是「直链文件存储」，文件带 downloadUrl 直链，TVBox 用 parse=0 直出。

★ 重要 —— 鉴权
    `ys/` 是【账号私有目录】，列表/详情接口必须带 access_token（Authorization 头）。
    配置本源时，把你的 KStore access_token 作为 extend 参数传入：
      · 源类型选「爬虫 / JS源（py）」，源地址填本文件；
      · extend / 附加参数 填：  token:<你的access_token>
    公开分享模式（无需 token）：
      extend 填：  share:<shareUuid>
      （即 KStore 把 ys/ 用“分享”生成公开链接后的 shareUuid，downloadUrl 通常仍可用）

★ 如何获取 access_token
    1) 浏览器登录 kstore.cc；
    2) 开发者工具 → Network，点一个 api.kstore.cc/api/v2 的请求；
    3) 复制 Request Headers 里的 Authorization 值（一串 JWT/十六进制）填到 extend。
    token 失效后在 TVBox 里更新 extend 即可。

★ 自测（无需 TVBox，先验证字段是否正确）
    set KSTORE_TOKEN=<token>
    set KSTORE_ROOT=ys/
    python kstore_ys.py
    会打印 /file/list 的原始 JSON 与前 10 个条目的字段；若字段名与我推断不符，
    按打印结果微调 _name/_path/_dl/_is_dir 即可。
"""
import json
import re
import urllib.parse

from base.spider import Spider


class Spider(Spider):

    API = "https://api.kstore.cc/api/v2"
    DEFAULT_ROOT = "ys/"          # 要浏览的根目录（与给定 URL 的 filePath 一致）
    UA = ("Mozilla/5.0 (Linux; Android 11) AppleWebKit/537.36 (KHTML, like Gecko) "
          "Chrome/126.0.0.0 Mobile Safari/537.36")

    # ============ 初始化 ============
    def getName(self):
        return "KStore直链网盘"

    def init(self, extend=""):
        self.token = ""
        self.share_uuid = ""
        self.root = self.DEFAULT_ROOT
        ex = (extend or "").strip()
        if ex.startswith("share:"):
            self.share_uuid = ex[6:].strip()
        elif ex.startswith("root:"):
            self.root = ex[5:].strip().strip("/") + "/"
        else:
            if ex.startswith("token:"):
                ex = ex[6:].strip()
            self.token = ex
        if not self.root.endswith("/"):
            self.root += "/"

    # ============ HTTP ============
    def _hdr(self, auth=True):
        h = {"User-Agent": self.UA,
             "Accept": "application/json, text/plain, */*",
             "Accept-Language": "zh-CN,zh;q=0.9"}
        if auth and self.token:
            h["Authorization"] = self.token
        return h

    def _get(self, endpoint, params, auth=True):
        url = self.API + endpoint + "?" + urllib.parse.urlencode(params)
        r = self.fetch(url, headers=self._hdr(auth))
        try:
            t = r.text
        except Exception:
            t = getattr(r, "content", b"").decode("utf-8", "ignore")
        try:
            return json.loads(t)
        except Exception:
            return {}

    # ============ 列表解析（字段名按 KStore 前端逆向推断，已做容错） ============
    @staticmethod
    def _items(j):
        if not isinstance(j, dict):
            return []
        data = j.get("data")
        if data is None:
            return []
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            items = None
            for k in ("list", "rows", "content", "records", "fileList", "files", "data"):
                v = data.get(k)
                if isinstance(v, list):
                    items = v
                    break
            items = items or []
        else:
            items = []
        return items

    @staticmethod
    def _is_dir(it):
        if it.get("isDir") is True:
            return True
        if str(it.get("type", "")).lower() == "folder":
            return True
        if it.get("folder") is True:
            return True
        return False

    @staticmethod
    def _name(it):
        return (it.get("name") or it.get("fileName") or "").strip()

    @staticmethod
    def _path(it):
        return (it.get("path") or "").strip()

    @staticmethod
    def _dl(it):
        return (it.get("downloadUrl") or it.get("url") or "").strip()

    def _list_folder(self, path, auth=None):
        if auth is None:
            auth = bool(self.token)
        if self.share_uuid:
            return self._items(self._get(
                "/share/public/file/list",
                {"shareUuid": self.share_uuid, "path": path}, auth=False))
        return self._items(self._get(
            "/file/list", {"filePath": path, "fileType": 0}, auth=auth))

    # ============ 目录树（生成 TVBox 分类） ============
    def _collect_folders(self, root, max_depth=4, max_cnt=80):
        out = []

        def walk(p, depth):
            if depth > max_depth or len(out) >= max_cnt:
                return
            try:
                items = self._list_folder(p)
            except Exception:
                return
            for it in items:
                if self._is_dir(it):
                    fp = self._path(it)
                    if fp and fp not in out:
                        out.append(fp)
                        walk(fp, depth + 1)

        walk(root, 1)
        return out

    # ============ TVBox 接口 ============
    def homeContent(self, filter):
        classes = [{"type_id": self.root, "type_name": "📁 " + self.root}]
        for fp in self._collect_folders(self.root):
            classes.append({"type_id": fp, "type_name": "📁 " + fp})
        if not classes:
            classes = [{"type_id": self.root, "type_name": self.root}]
        return {"class": classes}

    def homeVideoContent(self):
        return {"list": self._video_cards(self.root)}

    def categoryContent(self, tid, pg, filter, extend):
        path = tid or self.root
        videos = self._video_cards_from(self._list_folder(path))
        return {"list": videos, "page": 1, "pagecount": 1,
                "limit": len(videos) or 60, "total": len(videos)}

    def _video_cards_from(self, items):
        out = []
        for it in items:
            if self._is_dir(it):
                continue
            name = self._name(it)
            if not name:
                continue
            out.append({
                "vod_id": self._path(it),
                "vod_name": name,
                "vod_pic": "",
                "vod_remarks": it.get("extendName") or "",
            })
        return out

    def _video_cards(self, path):
        return self._video_cards_from(self._list_folder(path))

    def detailContent(self, ids):
        vid = ids[0] if isinstance(ids, (list, tuple)) and ids else ids
        vid = str(vid).strip()
        name = vid.rsplit("/", 1)[-1]
        # vod_id 即文件全路径；真实直链在 playerContent 里解析
        return {"list": [{
            "vod_id": vid,
            "vod_name": name,
            "vod_play_from": "直链",
            "vod_play_url": "1$" + vid,
        }]}

    def playerContent(self, flag, id, vipFlags):
        path = (id or "").strip()
        if self.share_uuid:
            j = self._get("/share/public/file/detail",
                          {"shareUuid": self.share_uuid, "path": path}, auth=False)
        else:
            j = self._get("/file/detail", {"path": path}, auth=bool(self.token))
        url = ""
        if isinstance(j, dict):
            d = j.get("data") or {}
            if isinstance(d, dict):
                url = (d.get("downloadUrl") or d.get("url") or "").strip()
        if not url.startswith("http"):
            return {"parse": 1, "url": self.API + "/file/detail?path=" + urllib.parse.quote(path)}
        header = {"User-Agent": self.UA, "Referer": "https://kstore.cc/"}
        if self.token:
            header["Authorization"] = self.token
        return {"parse": 0, "url": url, "header": header}

    def searchContent(self, key, quick, pg=1):
        key = (key or "").strip()
        if not key:
            return {"list": [], "page": 1}
        if self.share_uuid:
            items = self._list_folder(self.root)
            hit = [it for it in items if key in self._name(it)]
            return {"list": self._video_cards_from(hit), "page": 1}
        j = self._get("/file/search", {"keyword": key, "fileType": 0}, auth=bool(self.token))
        return {"list": self._video_cards_from(self._items(j)), "page": 1}

    def isVideoFormat(self, url):
        return bool(re.search(
            r"\.(m3u8|mp4|flv|mkv|ts|webm|mov|avi|rm|rmvb|wmv)(\?|$)", url or ""))

    def manualVideoCheck(self):
        return False

    def action(self, action):
        pass

    def destroy(self):
        pass


# ============ 本地自测（python kstore_ys.py） ============
if __name__ == "__main__":
    import os
    try:
        import ssl, gzip, urllib.request
        tok = os.environ.get("KSTORE_TOKEN", "")
        root = os.environ.get("KSTORE_ROOT", "ys/")
        c = ssl.create_default_context()
        c.check_hostname = False
        c.verify_mode = ssl.CERT_NONE

        def _raw(url, headers):
            req = urllib.request.Request(url, headers=headers)
            r = urllib.request.urlopen(req, timeout=25, context=c)
            data = r.read()
            if "gzip" in (r.headers.get("Content-Encoding") or ""):
                data = gzip.decompress(data)
            return data.decode("utf-8", "ignore")

        sp = Spider()
        sp.init(("token:" + tok) if tok else "")
        sp.root = root if root.endswith("/") else root + "/"

        def fet(url, headers=None):
            return type("R", (), {"text": _raw(url, headers or sp._hdr())})()

        sp.fetch = fet
        j = sp._get("/file/list", {"filePath": sp.root, "fileType": 0}, auth=bool(tok))
        print("LIST raw:", json.dumps(j, ensure_ascii=False)[:1500])
        items = sp._items(j)
        print("\nitems count:", len(items))
        for it in items[:10]:
            print(" name=%-30s isDir=%-5s path=%s dl=%s"
                  % (sp._name(it), sp._is_dir(it), sp._path(it), sp._dl(it)))
    except Exception as e:
        print("self-test error:", e)
