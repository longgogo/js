# coding=utf-8
# !/usr/bin/python
# 凡客TV (fktv.me) TVBox 源 —— 按电影猎手格式编写
# 接口: POST /ysapi/{endpoint}, 请求体 AES-128-ECB(base64) 加密 JSON, 响应同为 AES 或明文 JSON
#   - system/info     播放线路配置
#   - movie/search    列表/搜索(空关键词+cat_id=全量分类分页)
#   - movie/detail    详情+选集+签名播放地址(play_url, 3小时有效)
# 播放直链: https://fktv.me + playback_v2.play_url (m3u8, ts/key 为绝对地址)
# by WorkBuddy 2026-09-24
import sys
import os
sys.path.append("..")
import re
import json
import time
import random
import string
import base64
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
from base.spider import Spider


class Spider(Spider):

    host = "https://fktv.me"
    api_key = "9ed1a661a6ab787a"
    _cache = {}
    _cache_time = {}

    def getName(self):
        return "凡客TV"

    def init(self, extend=""):
        self.host = "https://fktv.me"
        self.api_key = "9ed1a661a6ab787a"
        try:
            self.device = ''.join(random.choices(string.hexdigits.lower()[:16], k=32))
        except Exception:
            self.device = 'a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6'
        self._routes = None
        self._info_time = 0
        self._cache = {}
        self._cache_time = {}

    def isVideoFormat(self, url):
        pass

    def manualVideoCheck(self):
        pass

    def action(self, action):
        pass

    def destroy(self):
        pass

    # ---------------- 基础工具 ----------------

    def header(self):
        return {
            'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                           '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9',
        }

    def _aes_enc(self, text):
        cipher = AES.new(self.api_key.encode(), AES.MODE_ECB)
        return base64.b64encode(cipher.encrypt(pad(text.encode('utf-8'), AES.block_size))).decode('utf-8')

    def _aes_dec(self, text):
        cipher = AES.new(self.api_key.encode(), AES.MODE_ECB)
        return unpad(cipher.decrypt(base64.b64decode(text)), AES.block_size).decode('utf-8')

    def _post_raw(self, url, body, headers):
        attempts = [
            ('post', (url, body), {'headers': headers}),
            ('post', (url,), {'data': body, 'headers': headers}),
            ('fetch', (url,), {'post': body, 'headers': headers}),
        ]
        for name, args, kwargs in attempts:
            try:
                fn = getattr(self, name)
            except Exception:
                continue
            # 优先带 timeout 快速失败(影视仓默认超时短, 长挂会被 UI 判定失败)
            for extra in ({'timeout': 10}, {}):
                try:
                    k = dict(kwargs)
                    k.update(extra)
                    r = fn(*args, **k)
                    if r is not None:
                        return r
                except TypeError:
                    continue
                except Exception:
                    break
        return None

    def _api(self, ep, data=None):
        payload = {
            "deviceId": self.device, "token": "", "domain": "fktv.me", "referer": "",
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36",
            "shareCode": "", "channel": "", "ip": "", "data": data if data else {},
        }
        body = self._aes_enc(json.dumps(payload))
        headers = {
            'version': '1.0', 'deviceType': 'pc',
            'time': time.strftime('%Y-%m-%d %H:%M:%S'),
            'shareCode': '', 'channel': '', 'ip': '',
            'Content-Type': 'application/octet-stream',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0',
        }
        req = self._post_raw(self.host + '/ysapi/' + ep, body, headers)
        text = ''
        if req is None:
            text = ''
        elif isinstance(req, str):
            text = req
        elif hasattr(req, 'text'):
            text = req.text
        text = (text or '').strip()
        if not text:
            raise Exception('empty response from ' + ep)
        if text.startswith('{') or text.startswith('['):
            return json.loads(text)
        return json.loads(self._aes_dec(text))

    def _api_retry(self, ep, data=None, times=2):
        last = None
        for i in range(times):
            try:
                r = self._api(ep, data)
                if r.get('status') == 'y':
                    return r
                last = r
            except Exception:
                last = None
            if i < times - 1:
                try:
                    time.sleep(0.5)
                except Exception:
                    pass
        if isinstance(last, dict):
            return last
        return {}

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

    def _clean(self, s):
        try:
            s = re.sub(r'<[^>]+>', '', str(s or ''))
            return s.replace('&nbsp;', ' ').strip()
        except Exception:
            return str(s or '').strip()

    def _card(self, it):
        try:
            if not it.get('name'):
                return None
            remark = ''
            if it.get('score') and str(it['score']) not in ('0', '0.00'):
                remark = '评分%s' % str(it['score'])[:3]
            if it.get('release_at'):
                remark = (it['release_at'] + ' ') + remark if remark else it['release_at']
            return {
                'vod_id': str(it.get('id') or it.get('movie_id') or ''),
                'vod_name': it.get('name'),
                'vod_pic': it.get('img_x_source') or it.get('img_y_source') or it.get('img_x') or '',
                'vod_remarks': remark.strip(),
                'vod_year': it.get('release_at') or '',
            }
        except Exception:
            return None

    def _list_page(self, data, times=2):
        result = {}
        try:
            d = self._api_retry('movie/search', data, times=times).get('data') or {}
            videos = []
            for it in (d.get('data') or []):
                v = self._card(it)
                if v:
                    videos.append(v)
            result['list'] = videos
            try:
                result['page'] = int(data.get('page', '1'))
                result['pagecount'] = int(d.get('last_page') or 1)
                result['total'] = int(d.get('total') or 0)
            except Exception:
                result['page'] = 1
                result['pagecount'] = 1
                result['total'] = 0
            result['limit'] = 24
        except Exception:
            result['list'] = []
            result['page'] = 1
            result['pagecount'] = 1
            result['limit'] = 24
            result['total'] = 0
        return result

    # ---------------- TVBox 接口 ----------------

    def homeContent(self, filter):
        result = {}
        try:
            classes = [
                {'type_name': '电影', 'type_id': '6'},
                {'type_name': '电视剧', 'type_id': '5'},
                {'type_name': '动漫', 'type_id': '7'},
                {'type_name': '综艺', 'type_id': '4'},
                {'type_name': '短剧', 'type_id': '9'},
                {'type_name': '纪录片', 'type_id': '8'},
                {'type_name': '电影解说', 'type_id': '11'},
            ]
            years = ['2026', '2025', '2024', '2023', '2022', '2021', '2020', '2019', '2018', '2017']
            langs = [('国语', '1'), ('粤语', '2'), ('英语', '3'), ('韩语', '4'), ('日语', '5'), ('泰语', '7'), ('其他语', '8')]
            filters = {}
            for c in classes:
                fl = [{'key': 'year', 'name': '年份',
                       'value': [{'n': y + '年', 'v': y} for y in years]}]
                fl.append({'key': 'language', 'name': '语言',
                           'value': [{'n': n, 'v': v} for n, v in langs]})
                filters[c['type_id']] = fl
            result['class'] = classes
            result['filters'] = filters
        except Exception:
            pass
        return result

    def homeVideoContent(self):
        cached = self._cache_get('home', 600)
        if cached is not None:
            return cached
        try:
            # 首页推荐只试 1 次, 失败立即返回空, 不阻塞首屏
            res = {'list': self._list_page({'keywords': '', 'page': '1', 'page_size': '24'}, times=1)['list']}
        except Exception:
            res = {'list': []}
        self._cache_set('home', res)
        return res

    def categoryContent(self, tid, pg, filter, extend):
        try:
            try:
                p = int(pg)
            except Exception:
                p = 1
            if p < 1:
                p = 1
            ext = extend or {}
            data = {'keywords': '', 'cat_id': str(tid), 'page': str(p), 'page_size': '24'}
            year = str(ext.get('year', '') or '').strip()
            if re.match(r'^\d{4}$', year):
                data['year'] = year
            lang = str(ext.get('language', '') or '').strip()
            if re.match(r'^\d$', lang):
                data['language'] = lang
            key = 'cat:%s:%s:%s:%s' % (tid, p, year, lang)
            cached = self._cache_get(key, 300)
            if cached is not None:
                return cached
            r = self._list_page(data)
            if r.get('list'):
                self._cache_set(key, r)
            return r
        except Exception:
            return {'list': [], 'page': 1, 'pagecount': 1, 'limit': 24, 'total': 0}

    def detailContent(self, ids):
        result = {'list': []}
        try:
            mid = str(ids[0]).split('@')[0]
            cached = self._cache_get('detail:' + mid, 900)
            if cached is not None:
                return cached
            d = (self._api_retry('movie/detail', {'id': mid, 'is_simple': 'y'}).get('data') or {})
            video = {'vod_id': mid}
            video['vod_name'] = self._clean(d.get('name'))
            video['vod_pic'] = d.get('img_x_source') or d.get('img_y_source') or d.get('img_x') or ''
            video['vod_year'] = str(d.get('release_at') or '')
            video['vod_area'] = self._clean(d.get('area'))
            video['vod_remarks'] = self._clean(d.get('child_title') or d.get('category'))
            sc = str(d.get('score') or '')
            if sc and sc not in ('0', '0.00'):
                video['vod_remarks'] = (video['vod_remarks'] + ' 评分' + sc[:3]).strip()
            desc = []
            if d.get('director'):
                desc.append('导演: ' + self._clean(d['director']))
            actors = d.get('actors')
            if isinstance(actors, list):
                actor_names = []
                for a in actors:
                    try:
                        if isinstance(a, dict) and a.get('name'):
                            actor_names.append(self._clean(a['name']))
                        elif isinstance(a, str) and a.strip():
                            actor_names.append(self._clean(a))
                    except Exception:
                        continue
                if actor_names:
                    desc.append('主演: ' + ' '.join(actor_names[:12]))
            elif isinstance(actors, str) and actors.strip():
                desc.append('主演: ' + self._clean(actors))
            if d.get('description'):
                desc.append(self._clean(d['description']))
            video['vod_content'] = '\n'.join(desc)
            # 选集
            names = []
            play_urls = []
            links = d.get('links') or []
            if links:
                names.append('凡客TV')
                play_urls.append('#'.join(
                    '%s$%s@%s' % (self._clean(l.get('name') or ('第%s集' % (i + 1))), mid, l.get('id'))
                    for i, l in enumerate(links) if l.get('id')))
            video['vod_play_from'] = '$$$'.join(names)
            video['vod_play_url'] = '$$$'.join(play_urls)
            result['list'] = [video]
            self._cache_set('detail:' + mid, result)
        except Exception:
            result['list'] = []
        return result

    def searchContent(self, key, quick, pg="1"):
        try:
            try:
                p = int(pg)
            except Exception:
                p = 1
            if p < 1:
                p = 1
            ckey = 's:%s:%s' % (str(key), p)
            cached = self._cache_get(ckey, 180)
            if cached is not None:
                return cached
            r = self._list_page({'keywords': str(key), 'page': str(p), 'page_size': '15'})
            r['page'] = p
            if r.get('list'):
                self._cache_set(ckey, r)
            return r
        except Exception:
            return {'list': [], 'page': 1}

    def playerContent(self, flag, id, vipFlags):
        result = {}
        try:
            mid, _, lid = str(id).partition('@')
            ckey = 'play:%s:%s' % (mid, lid)
            cached = self._cache_get(ckey, 1800)
            if cached is not None:
                return cached
            data = {'id': mid, 'is_simple': 'y'}
            if lid:
                data['link_id'] = lid
            d = (self._api_retry('movie/detail', data).get('data') or {})
            pv = d.get('playback_v2') or {}
            play = pv.get('play_url') or ''
            url = ''
            if play:
                url = self.host + play if play.startswith('/') else play
            if not url:
                # 兜底: 旧版 play_links
                pl = d.get('play_links') or []
                if pl and isinstance(pl, list):
                    u = pl[0].get('url') if isinstance(pl[0], dict) else str(pl[0])
                    if u:
                        url = u
            result['parse'] = 0 if url else 1
            result['url'] = url
            result['header'] = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36',
                'Referer': self.host + '/',
            }
            if url:
                self._cache_set(ckey, result)
        except Exception:
            result['parse'] = 1
            result['url'] = ''
        return result

    def localProxy(self, param):
        return [200, 'text/plain', '']
