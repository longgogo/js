# coding=utf-8
"""
KStore 直链网盘 —— TVBox Python 蜘蛛（DRPY / py 源）v2
=====================================================
站点：https://kstore.cc   API：https://api.kstore.cc/api/v2

★ 为什么必须配置凭据（实测结论）
    `ys/` 是账号私有目录。不带有效凭据调接口，服务端返回：
      {"success":false,"code":-1,"msg":"UserPermission: need access_token or access_token error"}
    所以本源支持两种模式，二选一，写进 TVBox 源的 extend（附加参数）：

    【模式A · 私有 token】extend 填：
        token:<你的access_token>
      token 获取：浏览器登录 kstore.cc → F12 → Application/存储 → Cookie，
      名为 Authorization 的那条就是（前端把该 cookie 值原样放进 Authorization 头）。
      也可以 F12 → Network → 任一 api.kstore.cc 请求 → Request Headers 的 Authorization。
      注意：是原始值，**不要**加 Bearer 前缀。

    【模式B · 公开分享（推荐，免 token）】先在 kstore.cc 网页里把 ys/ 文件夹
      生成一个公开分享链接，然后 extend 直接填分享链接：
        https://kstore.cc/share/<shareUuid>
      若分享带提取码，写成： https://kstore.cc/share/<shareUuid>?pwd=1234
        或： share:<shareUuid>:1234
      也支持简写：share:<shareUuid>

    可选：在 extend 里用分号追加 root:某目录/  指定要浏览的根目录（默认 ys/）。
      例： token:xxxx;root:ys/    或    https://kstore.cc/share/abc;root:ys/

★ 本地自测（无需 TVBox）：
      set KSTORE_TOKEN=<token>          （或 set KSTORE_SHARE=https://kstore.cc/share/xxx）
      set KSTORE_ROOT=ys/
      python kstore_ys.py
    会打印列表接口的原始返回与解析结果；TVBox 里显示"⚠️"卡片时，错误信息
    就是接口返回的 msg，把该输出发给维护者即可定位。
"""
import json
import re
import urllib.parse

try:
    from base.spider import Spider
except Exception:                     # 本地自测 / 非 TVBox 环境兜底
    class Spider(object):
        def fetch(self, url, **kw):
            raise NotImplementedError("self.fetch 仅在 TVBox 宿主内可用")


class Spider(Spider):

    API = "https://api.kstore.cc/api/v2"
    SITE = "https://kstore.cc"
    DEFAULT_ROOT = "ys/"
    UA = ("Mozilla/5.0 (Linux; Android 11) AppleWebKit/537.36 (KHTML, like Gecko) "
          "Chrome/126.0.0.0 Mobile Safari/537.36")

    # ================= 基础 =================

    def getName(self):
        return "KStore直链网盘"

    def init(self, extend=""):
        self.token = ""
        self.share_uuid = ""
        self.share_pwd = ""
        self.root = self.DEFAULT_ROOT
        self.last_error = ""
        self._cache = {}
        ex = (extend or "").strip()
        # extend 支持 ; 或换行分隔的多段：token:xx / share:uuid[:pwd] / 完整分享链接 / root:xx
        for part in re.split(r"[;\n]", ex):
            part = part.strip()
            if not part:
                continue
            low = part.lower()
            if low.startswith("token:"):
                self.token = part[6:].strip()
            elif low.startswith("root:"):
                self.root = part[5:].strip().strip("/") + "/"
            elif low.startswith("pwd:"):
                self.share_pwd = part[4:].strip()
            elif low.startswith("share:"):
                self._set_share(part[6:].strip())
            elif "kstore.cc/share/" in low or "/share/" in low:
                self._set_share(part)
            elif len(part) > 8 and ":" not in part:
                self.token = part            # 裸 token
        if self.root and not self.root.endswith("/"):
            self.root += "/"

    def _set_share(self, s):
        s = (s or "").strip()
        m = re.search(r"/share/([0-9A-Za-z\-_]+)", s)
        if m:
            self.share_uuid = m.group(1)
        else:
            self.share_uuid = s.split(":")[0].strip()
        mp = re.search(r"[?&]pwd=([^&\s]+)", s)
        if mp:
            self.share_pwd = mp.group(1)
        elif ":" in s.split("/")[-1]:
            tail = s.rstrip("/").split("/")[-1]
            if ":" in tail and not self.share_pwd:
                self.share_pwd = tail.split(":", 1)[1]

    def isVideoFormat(self, url):
        return True if re.search(
            r"\.(m3u8|mp4|flv|mkv|ts|webm|mov|avi|rm|rmvb|wmv)(\?|$)", url or "") else False

    def manualVideoCheck(self):
        return False

    def action(self, action):
        pass

    def destroy(self):
        pass

    def localProxy(self, param):
        return None

    # ================= HTTP =================

    def _raw(self, url, headers=None, timeout=20):
        """兼容不同宿主 fetch 签名；返回响应对象或 None。"""
        h = {"User-Agent": self.UA,
             "Accept": "application/json, text/plain, */*",
             "Accept-Language": "zh-CN,zh;q=0.9",
             "Referer": self.SITE + "/",
             "Origin": self.SITE}
        if headers:
            h.update(headers)
        for kw in ({"headers": h, "timeout": timeout, "allow_redirects": True},
                   {"headers": h, "timeout": timeout},
                   {"headers": h}):
            try:
                return self.fetch(url, **kw)
            except TypeError:
                continue
            except Exception:
                return None
        return None

    @staticmethod
    def _resp_text(r):
        if r is None:
            return ""
        try:
            t = r.text
            if t:
                return t
        except Exception:
            pass
        try:
            return (getattr(r, "content", b"") or b"").decode("utf-8", "ignore")
        except Exception:
            return ""

    def _hdr(self):
        h = {}
        if self.token:
            h["Authorization"] = self.token
        return h

    def _get(self, endpoint, params):
        url = self.API + endpoint + "?" + urllib.parse.urlencode(params)
        t = self._resp_text(self._raw(url, self._hdr()))
        try:
            j = json.loads(t)
        except Exception:
            j = {}
        if isinstance(j, dict) and j.get("success") is False:
            self.last_error = str(j.get("msg") or j.get("message") or "接口返回失败")
        else:
            self.last_error = ""
        return j

    # ================= 列表解析（深度容错：字段名不做假设） =================

    @staticmethod
    def _find_items(j):
        """在任意层级的返回里找『条目字典列表』。"""
        if not isinstance(j, dict):
            return []
        best = []

        def probe(node, depth):
            nonlocal best
            if depth > 6 or best:
                return
            if isinstance(node, list):
                dicts = [x for x in node if isinstance(x, dict)]
                if dicts and (any(k in dicts[0] for k in
                                  ("name", "fileName", "filename", "path", "filePath",
                                   "downloadUrl", "type", "isDir", "extendName"))):
                    if len(dicts) > len(best):
                        best = dicts
                for x in node[:30]:
                    probe(x, depth + 1)
            elif isinstance(node, dict):
                for k in ("list", "rows", "records", "content", "fileList", "files",
                          "data", "result", "items", "children"):
                    if k in node:
                        probe(node[k], depth + 1)
                if not best:
                    for v in node.values():
                        probe(v, depth + 1)

        probe(j.get("data", j), 0)
        return best

    @staticmethod
    def _is_dir(it):
        if it.get("isDir") is True or it.get("is_dir") is True or it.get("dir") is True:
            return True
        if it.get("isFile") is True:
            return False
        t = str(it.get("type") or it.get("fileType") or it.get("category") or "").lower()
        if t in ("folder", "dir", "directory"):
            return True
        if it.get("extendName") or it.get("downloadUrl") or it.get("size") is not None:
            return False
        return False

    @staticmethod
    def _name(it):
        for k in ("name", "fileName", "filename", "title"):
            v = it.get(k)
            if v:
                return str(v).strip()
        p = Spider._path(it)
        return p.rsplit("/", 1)[-1] if p else ""

    @staticmethod
    def _path(it):
        for k in ("path", "filePath", "fullPath", "parentPath"):
            v = it.get(k)
            if v and str(v).strip():
                return str(v).strip()
        return ""

    @staticmethod
    def _dl(it):
        for k in ("downloadUrl", "url", "directUrl", "previewUrl", "link"):
            v = it.get(k)
            if v and str(v).strip():
                return str(v).strip()
        return ""

    def _list_folder(self, path):
        key = (self.share_uuid, path)
        if key in self._cache:
            return self._cache[key]
        if self.share_uuid:
            params = {"shareUuid": self.share_uuid, "path": path or "/"}
            if self.share_pwd:
                params["password"] = self.share_pwd
            j = self._get("/share/public/file/list", params)
            if not self._find_items(j) and (path or "/") == "/":
                params["path"] = "."
                j = self._get("/share/public/file/list", params)
        else:
            j = self._get("/file/list", {"filePath": path, "fileType": 0})
        items = self._find_items(j)
        self._cache[key] = items
        return items

    # ================= 目录树 → TVBox 分类 =================

    def _folders(self, root, max_depth=3, max_cnt=60):
        out = []

        def walk(p, depth):
            if depth > max_depth or len(out) >= max_cnt:
                return
            for it in self._list_folder(p):
                if self._is_dir(it):
                    fp = self._path(it) or (p.rstrip("/") + "/" + self._name(it))
                    if fp and fp not in out:
                        out.append(fp)
                        walk(fp, depth + 1)

        walk(root, 1)
        return out

    # ================= 卡片 =================

    def _cards(self, items, with_dirs=False):
        out = []
        for it in items:
            name = self._name(it)
            if not name:
                continue
            if self._is_dir(it):
                if not with_dirs:
                    continue
                fp = self._path(it) or name
                out.append({"vod_id": "dir::" + fp, "vod_name": "📁 " + name,
                            "vod_pic": "", "vod_remarks": "文件夹"})
                continue
            rem = str(it.get("extendName") or "").upper()
            size = it.get("size")
            if isinstance(size, (int, float)) and size:
                rem = (rem + " " if rem else "") + (
                    "%.1fMB" % (size / 1048576.0) if size < 1073741824 else "%.2fGB" % (size / 1073741824.0))
            p = self._path(it) or (self.root.rstrip("/") + "/" + name)
            out.append({"vod_id": p, "vod_name": name, "vod_pic": "", "vod_remarks": rem})
        return out

    def _err_card(self):
        if not self.last_error:
            return []
        return [{"vod_id": "__err__", "vod_name": "⚠️ 列表获取失败",
                 "vod_pic": "", "vod_remarks": str(self.last_error)[:80]}]

    # ================= TVBox 接口 =================

    def homeContent(self, filter):
        classes = [{"type_id": self.root, "type_name": "📁 " + (self.root or "/")}]
        try:
            for fp in self._folders(self.root):
                nm = fp.rstrip("/").rsplit("/", 1)[-1]
                classes.append({"type_id": fp, "type_name": "📁 " + nm})
        except Exception:
            pass
        return {"class": classes}

    def homeVideoContent(self):
        return {"list": self._cards(self._list_folder(self.root)) + self._err_card()}

    def categoryContent(self, tid, pg, filter, extend):
        if str(tid or "").startswith("dir::"):
            tid = str(tid)[5:]
        path = tid or self.root
        items = self._list_folder(path)
        lst = self._cards(items, with_dirs=True) + self._err_card()
        return {"list": lst, "page": 1, "pagecount": 1,
                "limit": max(len(lst), 1), "total": len(lst)}

    def detailContent(self, ids):
        vid = ids[0] if isinstance(ids, (list, tuple)) and ids else ids
        vid = str(vid).strip()
        name = vid.rsplit("/", 1)[-1] or vid
        return {"list": [{
            "vod_id": vid,
            "vod_name": name,
            "vod_pic": "",
            "vod_content": "KStore 直链文件：" + vid,
            "vod_play_from": "KStore直链",
            "vod_play_url": "播放$" + vid,
        }]}

    def playerContent(self, flag, id, vipFlags):
        path = (id or "").strip()
        if self.share_uuid:
            params = {"shareUuid": self.share_uuid, "path": path}
            if self.share_pwd:
                params["password"] = self.share_pwd
            j = self._get("/share/public/file/detail", params)
        else:
            j = self._get("/file/detail", {"path": path})
        url = ""
        d = j.get("data") if isinstance(j, dict) else None
        for src in ([d] if isinstance(d, dict) else []) + self._find_items(j):
            url = self._dl(src)
            if url:
                break
        if url and not url.startswith("http"):
            url = "https:" + url if url.startswith("//") else ""
        # 兜底：previewUrl + Authorization 查询参数（前端同款做法）
        if not url and isinstance(d, dict) and d.get("previewUrl"):
            url = str(d["previewUrl"]) + ("&" if "?" in str(d["previewUrl"]) else "?") \
                  + "Authorization=" + urllib.parse.quote(self.token)
        if not url.startswith("http"):
            return {"parse": 1, "url": self.SITE + "/file?filePath=" +
                    urllib.parse.quote(path), "header": {"User-Agent": self.UA}}
        header = {"User-Agent": self.UA, "Referer": self.SITE + "/"}
        if self.token:
            header["Authorization"] = self.token
        return {"parse": 0, "url": url, "header": header}

    def searchContent(self, key, quick, pg=1):
        key = (key or "").strip()
        if not key or str(pg) not in ("1", "None", ""):
            return {"list": [], "page": 1}
        j = self._get("/file/search", {"keyword": key, "fileType": 0})
        return {"list": self._cards(self._find_items(j)), "page": 1}


# ================= 本地自测（python kstore_ys.py，无需 TVBox） =================
if __name__ == "__main__":
    import os
    import ssl
    import gzip
    import urllib.request

    tok = os.environ.get("KSTORE_TOKEN", "")
    share = os.environ.get("KSTORE_SHARE", "")
    root = os.environ.get("KSTORE_ROOT", "ys/")

    ext = ""
    if share:
        ext = share
    elif tok:
        ext = "token:" + tok
    ext += (";" if ext else "") + "root:" + root

    sp = Spider()
    try:
        sp.init(ext)
    except Exception as e:
        print("init error:", e)

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    def _local_fetch(url, headers=None, **kw):
        h = dict(headers or {})
        h.setdefault("Accept-Encoding", "gzip")
        req = urllib.request.Request(url, headers=h)
        r = urllib.request.urlopen(req, timeout=25, context=ctx)
        b = r.read()
        if "gzip" in (r.headers.get("Content-Encoding") or ""):
            try:
                b = gzip.decompress(b)
            except Exception:
                pass
        return type("R", (), {"text": b.decode("utf-8", "ignore"),
                              "content": b})()

    sp.fetch = _local_fetch

    print("mode:", "SHARE " + sp.share_uuid if sp.share_uuid else
          ("TOKEN " + (sp.token[:6] + "..." if sp.token else "无凭据")))
    print("root:", sp.root)
    j = sp._get("/share/public/file/list" if sp.share_uuid else "/file/list",
                ({"shareUuid": sp.share_uuid, "path": sp.root or "/"} if sp.share_uuid
                 else {"filePath": sp.root, "fileType": 0})
                if sp.share_pwd == "" or sp.share_uuid else
                {"shareUuid": sp.share_uuid, "path": sp.root or "/", "password": sp.share_pwd})
    print("RAW:", json.dumps(j, ensure_ascii=False)[:2000])
    items = sp._find_items(j)
    print("\nitems:", len(items))
    for it in items[:12]:
        print("  dir=%-5s name=%-34s path=%s dl=%s"
              % (sp._is_dir(it), sp._name(it), sp._path(it), sp._dl(it)[:70]))
    cards = sp._cards(items, with_dirs=True)
    print("\ncards:", len(cards))
    for c in cards[:12]:
        print("  ", c["vod_name"], "|", c["vod_remarks"], "|", c["vod_id"])
    if sp.last_error:
        print("\nlast_error:", sp.last_error)
