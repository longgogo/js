/* ============================================================
 * R1音乐+  |  MusicFree 聚合音源插件  v2.3.2
 * ------------------------------------------------------------
 * 五个子源合并为一个插件，靠 musicItem.source 字段分发：
 *   r1   → 自建 R1 音乐服务（N1 上的 node:3000，按歌手分组）
 *   bili → bilibili 音频（B站视频音轨）
 *   qq   → QQ音乐（官方榜 / 地区榜 / 特色榜 / 全球榜；源自 lukaizj/musicfree-plugins）
 *   ne   → 网易云音乐（64 个榜单 + 全标签歌单；源自 lukaizj/musicfree-plugins）
 *   mao  → 猫耳FM（missevan.com，有声/音乐，m3u8 流）
 *
 * 排行榜 / 热门歌单按源「分列」：每个分组标题带【来源】前缀，例如
 *   【R1本地】我的音乐 / 【B站】排行榜 / 【QQ】官方榜 / 【网易云】特色榜单
 *
 * 性能修复（榜单加载慢）：
 *   P1. bilibili getTopLists 里有一个**无 timeout** 的「每周必看」请求，接口一慢整页卡死 → 已彻底删除
 *   P2. R1 取列表改为「多个地址并发探测，谁先通用谁」，不再等外网隧道超时
 *   P3. R1 歌单列表 60s 内存缓存；排行榜整体 120s 缓存，反复切页 0ms
 *   P4. 排行榜/歌单标签请求全部并行（Promise.all），总耗时≈最慢的那个源
 *   P5. R1 服务端 /musiclist/search 实测 10~13s（实时校验）→ 改为「本地全量列表先过滤（毫秒级），未命中才回服务端」
 *   P6. R1 是慢源时不再拖死整页：榜单/歌单标签给 2.5s 软超时、搜索给 6s，超时先出其他源（R1 结果稍后进缓存）
 *
 * 单独修复：
 *   1. bilibili getMediaSource 在 quality 为 undefined 时 url 为空 → 默认取第 0 条音轨
 *   2. bilibili getTopListDetail 偶发 -352 → 带 buvid3/buvid4 cookie + 重试 3 次
 *   3. bilibili「每周必看」详情接口已强制 wbi 签名（稳定 -352）→ 不再暴露该分组
 *   4. QQ音乐搜索接口 client_search_cp 已被封（返回空）→ 换 search_for_qq_cp（实测 600 条总量）
 *   5. 网易云插件原本 require("qs")（MusicFree 沙箱无此模块）→ 改为内置 stringify
 *   6. 榜单/歌单详情改为逐条容错 map，单条脏数据不再拖垮整页
 *   7. 子源返回 {data:[...]} 或直接数组都兼容（猫耳 getRecommendSheetTags 返回对象）
 *   8. 猫耳 getMediaSource 在 high/super 音质下返回空 → 改为任何音质都回落可用地址
 *   9. 猫耳歌单列表/详情加重试；分页字段缺失时不再无限翻页
 *  10. R1 双地址自动切换：外网 DDNSTO 掉线时自动落到内网 http://192.168.1.3:3000
 *  11. 所有子源方法都包了 catch，任何一处抽风只影响自己那部分
 *
 * 安装：MusicFree → 设置 → 插件管理 → 从本地安装 → 选本文件
 * 配置：插件设置里可改「服务器地址（外网）」和「备用地址（内网）」
 * ============================================================ */

/* ===== 子源: buildBili ===== */
function buildBili() {
// [本地修复] 原版 getMediaSource 在 quality 为 undefined 时 url 取不到导致播不了；此处默认取第一条音轨。
"use strict";

const axios_1 = require("axios");
const dayjs = require("dayjs");
const he = require("he");
const CryptoJs = require("crypto-js");
const { load } = require('cheerio');
const headers = {
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/89.0.4389.90 Safari/537.36 Edg/89.0.774.63",
    accept: "*/*",
    "accept-encoding": "gzip, deflate, br",
    "accept-language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
};
let cookie;
async function getCid(bvid, aid) {
    const params = bvid
        ? {
            bvid: bvid,
        }
        : {
            aid: aid,
        };
    const cidRes = (await axios_1.default.get("https://api.bilibili.com/x/web-interface/view?%s", {
        headers: headers,
        params: params,
    })).data;
    return cidRes;
}
function durationToSec(duration) {
    if (typeof duration === "number") {
        return duration;
    }
    if (typeof duration === "string") {
        var dur = duration.split(":");
        return dur.reduce(function (prev, curr) {
            return 60 * prev + +curr;
        }, 0);
    }
    return 0;
}
const searchHeaders = {
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/89.0.4389.90 Safari/537.36 Edg/89.0.774.63",
    accept: "application/json, text/plain, */*",
    "accept-encoding": "gzip, deflate, br",
    origin: "https://search.bilibili.com",
    "sec-fetch-site": "same-site",
    "sec-fetch-mode": "cors",
    "sec-fetch-dest": "empty",
    referer: "https://search.bilibili.com/",
    "accept-language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6",
};
async function getCookie() {
    if (!cookie) {
        cookie = (await axios_1.default.get("https://api.bilibili.com/x/frontend/finger/spi", {
            headers: {
                "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 13_2_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/13.0.3 Mobile/15E148 Safari/604.1 Edg/114.0.0.0",
            },
        })).data.data;
    }
}
const pageSize = 20;
async function searchBase(keyword, page, searchType) {
    await getCookie();
    const params = {
        context: "",
        page: page,
        order: "",
        page_size: pageSize,
        keyword: keyword,
        duration: "",
        tids_1: "",
        tids_2: "",
        __refresh__: true,
        _extra: "",
        highlight: 1,
        single_column: 0,
        platform: "pc",
        from_source: "",
        search_type: searchType,
        dynamic_offset: 0,
    };
    const res = (await axios_1.default.get("https://api.bilibili.com/x/web-interface/search/type", {
        headers: Object.assign(Object.assign({}, searchHeaders), { cookie: `buvid3=${cookie.b_3};buvid4=${cookie.b_4}` }),
        params: params,
    })).data;
    return res.data;
}
async function getFavoriteList(id) {
    const result = [];
    const pageSize = 20;
    let page = 1;
    while (true) {
        try {
            const { data: { data: { medias, has_more }, }, } = await axios_1.default.get("https://api.bilibili.com/x/v3/fav/resource/list", {
                params: {
                    media_id: id,
                    platform: "web",
                    ps: pageSize,
                    pn: page,
                },
            });
            result.push(...medias);
            if (!has_more) {
                break;
            }
            page += 1;
        }
        catch (error) {
            console.warn(error);
            break;
        }
    }
    return result;
}
function formatMedia(result) {
    var _a, _b, _c, _d, _e, _f, _g, _h, _j, _k;
    const title = he.decode((_b = (_a = result.title) === null || _a === void 0 ? void 0 : _a.replace(/(\<em(.*?)\>)|(\<\/em\>)/g, "")) !== null && _b !== void 0 ? _b : "");
    return {
        id: (_d = (_c = result.cid) !== null && _c !== void 0 ? _c : result.bvid) !== null && _d !== void 0 ? _d : result.aid,
        aid: result.aid,
        bvid: result.bvid,
        artist: (_e = result.author) !== null && _e !== void 0 ? _e : (_f = result.owner) === null || _f === void 0 ? void 0 : _f.name,
        title,
        alias: (_g = title.match(/《(.+?)》/)) === null || _g === void 0 ? void 0 : _g[1],
        album: (_h = result.bvid) !== null && _h !== void 0 ? _h : result.aid,
        artwork: ((_j = result.pic) === null || _j === void 0 ? void 0 : _j.startsWith("//"))
            ? "http:".concat(result.pic)
            : result.pic,
        duration: durationToSec(result.duration),
        tags: (_k = result.tag) === null || _k === void 0 ? void 0 : _k.split(","),
        date: dayjs.unix(result.pubdate || result.created).format("YYYY-MM-DD"),
    };
}
async function searchAlbum(keyword, page) {
    const resultData = await searchBase(keyword, page, "video");
    const albums = resultData.result.map(formatMedia);
    return {
        isEnd: resultData.numResults <= page * pageSize,
        data: albums,
    };
}
async function searchArtist(keyword, page) {
    const resultData = await searchBase(keyword, page, "bili_user");
    const artists = resultData.result.map((result) => {
        var _a;
        return ({
            name: result.uname,
            id: result.mid,
            fans: result.fans,
            description: result.usign,
            avatar: ((_a = result.upic) === null || _a === void 0 ? void 0 : _a.startsWith("//"))
                ? `https://${result.upic}`
                : result.upic,
            worksNum: result.videos,
        });
    });
    return {
        isEnd: resultData.numResults <= page * pageSize,
        data: artists,
    };
}
function getMixinKey(e) {
    var t = [];
    return ([
        46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5,
        49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55,
        40, 61, 26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57,
        62, 11, 36, 20, 34, 44, 52,
    ].forEach(function (r) {
        e.charAt(r) && t.push(e.charAt(r));
    }),
        t.join("").slice(0, 32));
}
function hmacSha256(key, message) {
    const hmac = CryptoJs.HmacSHA256(message, key);
    return hmac.toString(CryptoJs.enc.Hex);
}
async function getBiliTicket(csrf) {
    const ts = Math.floor(Date.now() / 1000);
    const hexSign = hmacSha256('XgwSnGZ1p', `ts${ts}`);
    const url = 'https://api.bilibili.com/bapis/bilibili.api.ticket.v1.Ticket/GenWebTicket';
    try {
        const response = await axios_1.default.post(url, null, {
            params: {
                key_id: 'ec02',
                hexsign: hexSign,
                'context[ts]': ts,
                csrf: csrf || ''
            },
            headers: {
                'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/115.0'
            }
        });
        const data = await response.data;
        return data.data;
    }
    catch (e) {
        throw e;
    }
}
let img, sub, syncedTime;
async function getWBIKeys() {
    if (img && sub && syncedTime && syncedTime.getDate() === (new Date()).getDate()) {
        return {
            img,
            sub
        };
    }
    else {
        const data = await getBiliTicket('');
        img = data.nav.img;
        img = img.slice(img.lastIndexOf('/') + 1, img.lastIndexOf('.'));
        sub = data.nav.sub;
        sub = sub.slice(sub.lastIndexOf('/') + 1, sub.lastIndexOf('.'));
        syncedTime = new Date();
        return {
            img,
            sub
        };
    }
}
async function getRid(params) {
    const wbiKeys = await getWBIKeys();
    const npi = wbiKeys.img + wbiKeys.sub;
    const o = getMixinKey(npi);
    const l = Object.keys(params).sort();
    let c = [];
    for (let d = 0, u = /[!'\(\)*]/g; d < l.length; ++d) {
        let [h, p] = [l[d], params[l[d]]];
        p && "string" == typeof p && (p = p.replace(u, "")),
            null != p &&
                c.push("".concat(encodeURIComponent(h), "=").concat(encodeURIComponent(p)));
    }
    const f = c.join("&");
    const w_rid = CryptoJs.MD5(f + o).toString();
    return w_rid;
}
let w_webid;
let w_webid_date;
async function getWWebId(id) {
    if (w_webid && w_webid_date && (Date.now() - w_webid_date.getTime() < 1000 * 60 * 60)) {
        return w_webid;
    }
    const html = (await axios_1.default.get("https://space.bilibili.com/" + id, {
        headers: {
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/89.0.4389.90 Safari/537.36 Edg/89.0.774.63",
        }
    })).data;
    const $ = load(html);
    const content = $("#__RENDER_DATA__").text();
    const jsonContent = JSON.parse(decodeURIComponent(content));
    w_webid = jsonContent.access_id;
    w_webid_date = new Date();
    return w_webid;
}
async function getArtistWorks(artistItem, page, type) {
    const queryHeaders = {
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/89.0.4389.90 Safari/537.36 Edg/89.0.774.63",
        accept: "*/*",
        "accept-encoding": "gzip, deflate, br, zstd",
        origin: "https://space.bilibili.com",
        "sec-fetch-site": "same-site",
        "sec-fetch-mode": "cors",
        "sec-fetch-dest": "empty",
        referer: `https://space.bilibili.com/${artistItem.id}/video`,
    };
    await getCookie();
    const now = Math.round(Date.now() / 1e3);
    const params = {
        mid: artistItem.id,
        ps: 30,
        tid: 0,
        pn: page,
        web_location: 1550101,
        order_avoided: true,
        order: "pubdate",
        keyword: "",
        platform: "web",
        dm_img_list: "[]",
        dm_img_str: "V2ViR0wgMS4wIChPcGVuR0wgRVMgMi4wIENocm9taXVtKQ",
        dm_cover_img_str: "QU5HTEUgKE5WSURJQSwgTlZJRElBIEdlRm9yY2UgR1RYIDE2NTAgKDB4MDAwMDFGOTEpIERpcmVjdDNEMTEgdnNfNV8wIHBzXzVfMCwgRDNEMTEpR29vZ2xlIEluYy4gKE5WSURJQS",
        dm_img_inter: '{"ds":[],"wh":[0,0,0],"of":[0,0,0]}',
        wts: now.toString(),
    };
    const w_rid = await getRid(params);
    const res = (await axios_1.default.get("https://api.bilibili.com/x/space/wbi/arc/search", {
        headers: Object.assign(Object.assign({}, queryHeaders), { cookie: `buvid3=${cookie.b_3};buvid4=${cookie.b_4}` }),
        params: Object.assign(Object.assign({}, params), { w_rid }),
    })).data;
    console.log(res);
    const resultData = res.data;
    const albums = resultData.list.vlist.map(formatMedia);
    return {
        isEnd: resultData.page.pn * resultData.page.ps >= resultData.page.count,
        data: albums,
    };
}
async function getMediaSource(musicItem, quality) {
    var _a;
    let cid = musicItem.cid;
    if (!cid) {
        cid = (await getCid(musicItem.bvid, musicItem.aid)).data.cid;
    }
    const _params = musicItem.bvid
        ? {
            bvid: musicItem.bvid,
        }
        : {
            aid: musicItem.aid,
        };
    const res = (await axios_1.default.get("https://api.bilibili.com/x/player/playurl", {
        headers: headers,
        params: Object.assign(Object.assign({}, _params), { cid: cid, fnval: 16 }),
    })).data;
    let url;
    if (res.data.dash) {
        const audios = res.data.dash.audio;
        audios.sort((a, b) => a.bandwidth - b.bandwidth);
        const _pick = { low: 0, standard: 1, high: 2, super: 3 };
        let _idx = _pick[quality];
        if (_idx === undefined || _idx >= audios.length) _idx = 0;
        url = audios[_idx].baseUrl;
    }
    else {
        url = res.data.durl[0].url;
    }
    const hostUrl = url.substring(url.indexOf("/") + 2);
    const _headers = {
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/89.0.4389.90 Safari/537.36 Edg/89.0.774.63",
        accept: "*/*",
        host: hostUrl.substring(0, hostUrl.indexOf("/")),
        "accept-encoding": "gzip, deflate, br",
        connection: "keep-alive",
        referer: "https://www.bilibili.com/video/".concat((_a = (musicItem.bvid !== null && musicItem.bvid !== undefined
            ? musicItem.bvid
            : musicItem.aid)) !== null && _a !== void 0 ? _a : ""),
    };
    return {
        url: url,
        headers: _headers,
    };
}
async function getTopLists() {
    const precious = {
        title: "入站必刷",
        data: [
            {
                id: "popular/precious?page_size=100&page=1",
                title: "入站必刷",
                coverImg: "https://s1.hdslb.com/bfs/static/jinkela/popular/assets/icon_history.png",
            },
        ],
    };
    const weekly = {
        title: "每周必看",
        data: [],
    };
    // [本地修复·性能] 原版这里无条件请求 popular/series/list（且无 timeout），接口一慢整个排行榜就卡住，
    // 而该分组的详情接口已强制 wbi 签名必然 -352，属于纯浪费。直接不请求、不返回。 
    // （weekly 变量保留，仅为说明历史逻辑，不再计入返回值）
    const boardKeys = [
        {
            id: "ranking/v2?rid=0&type=all",
            title: "全站",
        },
        {
            id: "ranking/v2?rid=3&type=all",
            title: "音乐",
        },
        {
            id: "ranking/v2?rid=1&type=all",
            title: "动画",
        },
        {
            id: "ranking/v2?rid=119&type=all",
            title: "鬼畜",
        },
        {
            id: "ranking/v2?rid=168&type=all",
            title: "国创相关",
        },
        {
            id: "ranking/v2?rid=129&type=all",
            title: "舞蹈",
        },
        {
            id: "ranking/v2?rid=4&type=all",
            title: "游戏",
        },
        {
            id: "ranking/v2?rid=36&type=all",
            title: "知识",
        },
        {
            id: "ranking/v2?rid=188&type=all",
            title: "科技",
        },
        {
            id: "ranking/v2?rid=234&type=all",
            title: "运动",
        },
        {
            id: "ranking/v2?rid=223&type=all",
            title: "汽车",
        },
        {
            id: "ranking/v2?rid=160&type=all",
            title: "生活",
        },
        {
            id: "ranking/v2?rid=211&type=all",
            title: "美食",
        },
        {
            id: "ranking/v2?rid=217&type=all",
            title: "动物圈",
        },
        {
            id: "ranking/v2?rid=155&type=all",
            title: "时尚",
        },
        {
            id: "ranking/v2?rid=5&type=all",
            title: "娱乐",
        },
        {
            id: "ranking/v2?rid=181&type=all",
            title: "影视",
        },
        {
            id: "ranking/v2?rid=0&type=origin",
            title: "原创",
        },
        {
            id: "ranking/v2?rid=0&type=rookie",
            title: "新人",
        },
    ];
    const board = {
        title: "排行榜",
        data: boardKeys.map((_) => (Object.assign(Object.assign({}, _), { coverImg: "https://s1.hdslb.com/bfs/static/jinkela/popular/assets/icon_rank.png" }))),
    };
    // [本地修复] 「每周必看」详情接口 popular/series/one 现在稳定返回 -352（需 wbi 签名），
    // 点进去必然空白，故不再暴露该分组；weekly 变量保留仅作说明。
    return [precious, board];
}
async function getTopListDetail(topListItem) {
    // [本地修复] 原版直接用 res.data.data.list.map，遇风控/结构变化会抛错导致榜单空白。
    // 现在：带 buvid cookie（不带时该接口高频返回 -352）+ 结构容错 + 失败重试。
    let list = [];
    for (let attempt = 0; attempt < 3; attempt++) {
        try {
            await getCookie();
            const res = await axios_1.default.get(`https://api.bilibili.com/x/web-interface/${topListItem.id}`, {
                headers: Object.assign(Object.assign({}, headers), {
                    referer: "https://www.bilibili.com/",
                    cookie: `buvid3=${cookie.b_3};buvid4=${cookie.b_4}`,
                }),
            });
            const data = res && res.data && res.data.data;
            list = (data && data.list) || [];
            if (list.length) break;
        }
        catch (e) {
            list = [];
        }
        // sandbox 不一定提供 setTimeout，缺失时直接跳过退避
        if (attempt < 2 && typeof setTimeout === "function") {
            try {
                await new Promise(r => setTimeout(r, 800 * (attempt + 1)));
            }
            catch (e) { }
        }
    }
    // [本地修复] 逐条 map，单条数据异常不再拖垮整个榜单
    const musicList = [];
    for (const item of list) {
        if (!item) continue;
        try {
            const one = formatMedia(item);
            if (one && one.id) musicList.push(one);
        }
        catch (e) { }
    }
    return Object.assign(Object.assign({}, topListItem), { isEnd: true, musicList });
}
async function importMusicSheet(urlLike) {
    var _a, _b, _c, _d;
    let id;
    if (!id) {
        id = (_a = urlLike.match(/^\s*(\d+)\s*$/)) === null || _a === void 0 ? void 0 : _a[1];
    }
    if (!id) {
        id = (_b = urlLike.match(/^(?:.*)fid=(\d+).*$/)) === null || _b === void 0 ? void 0 : _b[1];
    }
    if (!id) {
        id = (_c = urlLike.match(/\/playlist\/pl(\d+)/i)) === null || _c === void 0 ? void 0 : _c[1];
    }
    if (!id) {
        id = (_d = urlLike.match(/\/list\/ml(\d+)/i)) === null || _d === void 0 ? void 0 : _d[1];
    }
    if (!id) {
        return;
    }
    const musicSheet = await getFavoriteList(id);
    return musicSheet.map((_) => {
        var _a, _b;
        return ({
            id: _.id,
            aid: _.aid,
            bvid: _.bvid,
            artwork: _.cover,
            title: _.title,
            artist: (_a = _.upper) === null || _a === void 0 ? void 0 : _a.name,
            album: (_b = _.bvid) !== null && _b !== void 0 ? _b : _.aid,
            duration: durationToSec(_.duration),
        });
    });
}
function formatComment(item) {
    var _a, _b, _c, _d, _e;
    return {
        id: item.rpid,
        nickName: (_a = item.member) === null || _a === void 0 ? void 0 : _a.uname,
        avatar: (_b = item.member) === null || _b === void 0 ? void 0 : _b.avatar,
        comment: (_c = item.content) === null || _c === void 0 ? void 0 : _c.message,
        like: item.like,
        createAt: item.ctime * 1000,
        location: ((_e = (_d = item.reply_control) === null || _d === void 0 ? void 0 : _d.location) === null || _e === void 0 ? void 0 : _e.startsWith("IP属地：")) ? item.reply_control.location.slice(5) : undefined
    };
}
async function getMusicComments(musicItem) {
    var _a, _b;
    const params = {
        type: 1,
        mode: 3,
        oid: musicItem.aid,
        plat: 1,
        web_location: 1315875,
        wts: Math.floor(Date.now() / 1000)
    };
    const w_rid = await getRid(params);
    const res = (await (axios_1.default.get("https://api.bilibili.com/x/v2/reply/wbi/main", {
        params: Object.assign(Object.assign({}, params), { w_rid })
    }))).data;
    const data = res.data.replies;
    const comments = [];
    for (let i = 0; i < data.length; ++i) {
        comments[i] = formatComment(data[i]);
        if ((_a = data[i].replies) === null || _a === void 0 ? void 0 : _a.length) {
            comments[i].replies = (_b = data[i]) === null || _b === void 0 ? void 0 : _b.replies.map(formatComment);
        }
    }
    return {
        isEnd: true,
        data: comments
    };
}
return {
    platform: "bilibili",
    appVersion: ">=0.0",
    version: "0.2.3",
    author: "猫头猫",
    cacheControl: "no-cache",
    srcUrl: "https://gitee.com/maotoumao/MusicFreePlugins/raw/v0.1/dist/bilibili/index.js",
    primaryKey: ["id", "aid", "bvid", "cid"],
    hints: {
        importMusicSheet: [
            "bilibili 移动端：APP点击我的，空间，右上角分享，复制链接，浏览器打开切换桌面版网站，点击播放全部视频，复制链接",
            "bilibili H5/PC端：复制收藏夹URL，或者直接输入ID即可",
            "非公开收藏夹无法导入，编辑收藏夹改为公开即可",
            "导入时间和歌单大小有关，请耐心等待",
        ],
    },
    supportedSearchType: ["music", "album", "artist"],
    async search(keyword, page, type) {
        if (type === "album" || type === "music") {
            return await searchAlbum(keyword, page);
        }
        if (type === "artist") {
            return await searchArtist(keyword, page);
        }
    },
    getMediaSource,
    async getAlbumInfo(albumItem) {
        var _a;
        const cidRes = await getCid(albumItem.bvid, albumItem.aid);
        const _ref2 = (_a = cidRes === null || cidRes === void 0 ? void 0 : cidRes.data) !== null && _a !== void 0 ? _a : {};
        const cid = _ref2.cid;
        const pages = _ref2.pages;
        let musicList;
        if (pages.length === 1) {
            musicList = [Object.assign(Object.assign({}, albumItem), { cid: cid })];
        }
        else {
            musicList = pages.map(function (_) {
                return Object.assign(Object.assign({}, albumItem), { cid: _.cid, title: _.part, duration: durationToSec(_.duration), id: _.cid });
            });
        }
        return {
            musicList,
        };
    },
    getArtistWorks,
    getTopLists,
    getTopListDetail,
    importMusicSheet,
    getMusicComments
};

}

/* ===== 子源: buildMao ===== */
function buildMao() {
"use strict";

const axios_1 = require("axios");
const pageSize = 30;
function validMusicFilter(_) {
    return `${_.pay_type}` === "0";
}
function formatMusicItem(_) {
    var _a;
    return {
        id: _.id,
        artwork: _.front_cover,
        title: _.soundstr,
        artist: _.username,
        user_id: _.user_id,
        duration: +((_a = _.duration) !== null && _a !== void 0 ? _a : 0),
    };
}
function formatAlbumItem(_) {
    return {
        id: _.id,
        artist: _.author,
        title: _.name,
        artwork: _.cover,
        description: _.abstract,
    };
}
const searchHeaders = {
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36 Edg/109.0.1518.61",
    accept: "application/json",
    "accept-encoding": "gzip, deflate, br",
    referer: "https://www.missevan.com/sound/search",
};
async function searchMusic(query, page) {
    const res = (await axios_1.default.get("https://www.missevan.com/sound/getsearch", {
        params: {
            s: query,
            p: page,
            type: 3,
            page_size: pageSize,
        },
        headers: searchHeaders,
    })).data.info;
    return {
        isEnd: res.pagination.p >= res.pagination.maxpage,
        data: res.Datas.filter(validMusicFilter).map(formatMusicItem),
    };
}
async function searchAlbum(query, page) {
    const res = (await axios_1.default.get("https://www.missevan.com/dramaapi/search", {
        headers: searchHeaders,
        params: {
            s: query,
            page,
        },
    })).data.info;
    return {
        isEnd: res.pagination.p >= res.pagination.maxpage,
        data: res.Datas.filter(validMusicFilter).map(formatAlbumItem),
    };
}
async function getAlbumInfo(albumItem) {
    const res = (await axios_1.default.get("https://www.missevan.com/dramaapi/getdrama", {
        headers: {
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36 Edg/109.0.1518.61",
            accept: "application/json",
            "accept-encoding": "gzip, deflate, br",
            referer: `https://www.missevan.com/mdrama/${albumItem.id}`,
        },
        params: {
            drama_id: albumItem.id,
        },
    })).data;
    return {
        musicList: res.info.episodes.episode
            .filter(validMusicFilter)
            .map(_ => {
            const r = formatMusicItem(_);
            r.artwork = albumItem.artwork;
            return r;
        }),
    };
}
async function getMediaSource(musicItem, quality) {
    // [本地修复] 原版在 quality 为 high/super 时直接 return undefined，用户把音质调高就播不了。
    // 现在任何音质都回落到可用地址，取不到时用搜索结果里自带的 url 兜底。
    try {
        const res = (await axios_1.default.get("https://www.missevan.com/sound/getsound", {
            headers: {
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36 Edg/109.0.1518.61",
                accept: "application/json",
                "accept-encoding": "gzip, deflate, br",
                referer: `https://www.missevan.com/sound/player?id=${musicItem.id}`,
            },
            params: {
                soundid: musicItem.id,
            },
        })).data.info;
        const s = res && res.sound;
        if (s) {
            const url = quality === "low"
                ? (s.soundurl_128 || s.soundurl)
                : (s.soundurl || s.soundurl_128);
            if (url) return { url };
        }
    }
    catch (e) { }
    return { url: (musicItem && musicItem.url) || "" };
}
/* [本地新增] 猫耳接口偶发 412/空响应，统一重试 3 次 */
async function maoGet(url, config, pick) {
    for (let i = 0; i < 3; i++) {
        try {
            const v = pick(await axios_1.default.get(url, config));
            if (v) return v;
        }
        catch (e) { }
        if (i < 2 && typeof setTimeout === "function") {
            try { await new Promise(r => setTimeout(r, 600 * (i + 1))); } catch (e) { }
        }
    }
    return null;
}
async function getRecommendSheetTags() {
    const res = await maoGet(`https://www.missevan.com/malbum/recommand`, {
        headers: {
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36 Edg/109.0.1518.61",
            accept: "application/json",
            "accept-encoding": "gzip, deflate, br",
            referer: `https://www.missevan.com`,
        }
    }, r => {
        const d = r && r.data;
        return (d && d.info && Object.keys(d.info).length) ? d.info : null;
    });
    const data = Object.entries(res || {}).map(group => ({
        title: group[0],
        data: (Array.isArray(group[1]) ? group[1] : []).filter(Boolean).map(_ => ({
            id: _[0],
            title: _[1]
        }))
    })).filter(g => g.data.length);
    return {
        data,
    };
}
async function getRecommendSheetsByTag(tag, page) {
    const res = await maoGet(`https://www.missevan.com/explore/tagalbum`, {
        headers: {
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36 Edg/109.0.1518.61",
            accept: "application/json",
            "accept-encoding": "gzip, deflate, br",
            referer: `https://m.missevan.com`,
        },
        params: {
            order: 0,
            tid: (tag === null || tag === void 0 ? void 0 : tag.id) || 0,
            p: page
        }
    }, r => {
        const d = r && r.data;
        return (d && Array.isArray(d.albums)) ? d : null;
    });
    const albums = (res && Array.isArray(res.albums)) ? res.albums : [];
    return {
        // [本地修复] 原版 res.page >= res.maxpage，接口不返回这两个字段时恒为 false，会导致无限翻页
        isEnd: !res || !(res.page < res.maxpage),
        data: albums.map(sheet => ({
            id: sheet.id,
            title: sheet.title,
            artwork: sheet.front_cover,
            artist: sheet.username,
            createUserId: sheet.user_id
        }))
    };
}
async function getMusicSheetInfo(sheet, page) {
    const res = await maoGet(`https://www.missevan.com/sound/soundalllist`, {
        headers: {
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/109.0.0.0 Safari/537.36 Edg/109.0.1518.61",
            accept: "application/json",
            "accept-encoding": "gzip, deflate, br",
            referer: `https://m.missevan.com`,
        },
        params: {
            albumid: sheet.id
        }
    }, r => {
        const d = r && r.data;
        return (d && d.success && d.info && Array.isArray(d.info.sounds) && d.info.sounds.length) ? d.info : null;
    });
    // [本地修复] sounds 缺失/非数组时原版会直接抛错导致整个歌单空白；且付费专辑 soundurl 为空，
    // 全部被 validMusicFilter 滤掉后会得到空列表，这里统一做容错。
    const sounds = res && Array.isArray(res.sounds) ? res.sounds : [];
    const musicList = [];
    for (const item of sounds) {
        if (!item) continue;
        try {
            if (!validMusicFilter(item)) continue;
            musicList.push({
                id: item.id,
                title: item.soundstr,
                artwork: item.front_cover,
                url: item.soundurl,
                artist: item.username,
            });
        }
        catch (e) { }
    }
    return {
        isEnd: true,
        musicList,
    };
}
return {
    platform: "猫耳FM",
    author: '猫头猫',
    version: "0.1.4",
    appVersion: ">0.1.0-alpha.0",
    srcUrl: "https://gitee.com/maotoumao/MusicFreePlugins/raw/v0.1/dist/maoerfm/index.js",
    cacheControl: "no-cache",
    supportedSearchType: ["music", "album",],
    async search(query, page, type) {
        if (type === "music") {
            return await searchMusic(query, page);
        }
        if (type === "album") {
            return await searchAlbum(query, page);
        }
    },
    getMediaSource,
    getAlbumInfo,
    getRecommendSheetTags,
    getRecommendSheetsByTag,
    getMusicSheetInfo
};

}

/* ===== 子源: buildR1 ===== */
function buildR1() {
/*
 * R1本地音乐 —— MusicFree 音源插件  v1.2.0
 * 对接自建 R1 音乐服务（酷我/HYW 双通道，已过滤 VIP 试听片段）
 *
 * 安装：MusicFree → 设置 → 插件管理 → + → 从本地文件安装 → 选本文件
 * 配置：插件设置里可改「服务器地址」，默认已指向 DDNSTO 域名
 * 使用：首页搜索；或「排行榜 / 热门歌单 → R1本地音乐」按歌手浏览歌单
 *
 * v1.2.0 变动：
 *   - getTopListDetail / getRecommendSheetDetail 改为「合并榜单对象 + musicList」
 *     （对齐官方插件写法；原先返回 {isEnd,musicList} 缺 id/title，桌面版渲染不出内容）。
 *   - 排行榜、热门歌单改为「按歌手分组」生成多个真实歌单，每张带生成的封面。
 */

var PLATFORM = "R1本地音乐";
var DEFAULT_BASE = "https://52npwvr1.gd.ddnsto.com";
var LOCAL_BASE = "http://192.168.1.3:3000";
var PAGE_SIZE = 20;
var BASE_OK = ""; // 记住最近一次真正连通的地址（DDNSTO 掉线时自动落到内网）

/* ---------------- 基础工具 ---------------- */

function getUserVar(key) {
  try {
    if (typeof env !== "undefined" && env && env.getUserVariables) {
      var v = env.getUserVariables();
      if (v && v[key]) return String(v[key]).replace(/\/+$/, "");
    }
  } catch (e) {}
  return "";
}

function getBase() {
  return BASE_OK || getUserVar("baseUrl") || DEFAULT_BASE;
}

// 依次尝试：当前可用地址 → 内网地址 → DDNSTO 地址
function bases() {
  var list = [getBase(), getUserVar("localBase") || LOCAL_BASE, getUserVar("baseUrl") || DEFAULT_BASE];
  var out = [];
  for (var i = 0; i < list.length; i++) {
    if (list[i] && out.indexOf(list[i]) < 0) out.push(list[i]);
  }
  return out;
}

function fixUrl(u) {
  if (!u) return "";
  u = String(u);
  // 服务端按自己的视角可能返回 127.0.0.1/localhost 地址，统一改写到当前可用 base
  if (/^https?:\/\/(127\.0\.0\.1|localhost)(:\d+)?\//i.test(u)) {
    u = getBase() + u.replace(/^https?:\/\/[^\/]+/i, "");
  }
  if (/^http:\/\/[^\/]*ddnsto\.com/i.test(u)) u = u.replace(/^http:/i, "https:");
  return u;
}

function assignObj(target) {
  for (var i = 1; i < arguments.length; i++) {
    var s = arguments[i];
    if (s) for (var k in s) target[k] = s[k];
  }
  return target;
}

// 用歌手首字生成一张简单 SVG 封面（服务本身无封面）
function makeCover(text) {
  var ch = (text || "?").slice(0, 1) || "?";
  var svg =
    '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200">' +
    '<rect width="200" height="200" fill="#2b6cb0"/>' +
    '<text x="100" y="128" font-size="96" fill="#ffffff" text-anchor="middle" font-family="sans-serif">' +
    ch + "</text></svg>";
  return "data:image/svg+xml;utf8," + encodeURIComponent(svg);
}

function getAxios() {
  try {
    if (typeof require === "function") return require("axios");
  } catch (e) {}
  return null;
}

function parseBody(data) {
  if (data == null) return null;
  if (typeof data === "string") {
    try {
      return JSON.parse(data);
    } catch (e) {
      return null;
    }
  }
  return data;
}

function httpGetJson(url, timeoutMs) {
  var headers = {
    "User-Agent":
      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    Accept: "application/json, text/plain, */*",
  };
  var to = timeoutMs || 40000;

  var axios = getAxios();
  if (axios && typeof axios.get === "function") {
    return axios
      .get(url, { timeout: to, headers: headers })
      .then(function (res) {
        return parseBody(res && res.data);
      });
  }
  if (typeof fetch === "function") {
    return fetch(url, { headers: headers }).then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    });
  }
  if (typeof env !== "undefined" && env && typeof env.request === "function") {
    return Promise.resolve(
      env.request(url, { headers: headers, timeout: to })
    ).then(parseBody);
  }
  return Promise.reject(new Error("当前环境没有可用的网络模块(axios)"));
}

/* 带地址回退的 R1 请求：多个地址并发打，谁先成功用谁（避免外网超时拖慢） */
function r1Get(path, timeoutMs) {
  var bs = bases();
  var to = timeoutMs || 5000;
  return new Promise(function (resolve, reject) {
    var settled = false;
    var failed = 0;
    bs.forEach(function (b) {
      httpGetJson(b + path, to)
        .then(function (json) {
          if (settled) return;
          settled = true;
          BASE_OK = b;
          resolve(json);
        })
        .catch(function (e) {
          if (settled) return;
          failed++;
          if (failed >= bs.length) {
            settled = true;
            reject(e || new Error("R1 服务不可达"));
          }
        });
    });
  });
}

/* [性能] 歌单列表缓存 60s：排行榜/热门歌单/搜索兜底都会拉全量，重复请求纯属浪费 */
var LIST_CACHE = { at: 0, data: null };
var LIST_TTL = 60 * 1000;
function fetchAll(force) {
  var now = Date.now();
  if (!force && LIST_CACHE.data && now - LIST_CACHE.at < LIST_TTL) {
    return Promise.resolve(LIST_CACHE.data);
  }
  return r1Get("/musiclist?size=2000").then(function (json) {
    var list = mapList(extractList(json));
    LIST_CACHE = { at: Date.now(), data: list };
    return list;
  });
}

/* ---------------- 数据转换 ---------------- */

function extractList(json) {
  if (!json || typeof json !== "object") return [];
  var cands = [
    json.musicList,
    json.musicinfo,
    json.songs,
    json.result,
    json.itemList,
    json.data && json.data.list,
    json.data && json.data.musicList,
    json.data && json.data.musicinfo,
    json.data && json.data.songs,
  ];
  for (var i = 0; i < cands.length; i++) {
    var c = cands[i];
    if (c && c.length) return Array.prototype.slice.call(c);
  }
  return [];
}

function toItem(it) {
  if (!it || typeof it !== "object") return null;
  var rid = it.rid || (it.songId ? "MUSIC_" + it.songId : "") || it.id || "";
  var playUrl = fixUrl(it.url || it.directUrl || it.playUrl || "");
  if (!playUrl && rid) playUrl = getBase() + "/play/" + rid;

  var title = it.title || it.name || "";
  if (!title) return null;

  var id = String(it.id || it.songId || rid || title);
  var dur = Number(it.duration || it.interval || 0);

  return {
    id: id,
    title: title,
    artist: it.artist || it.singer || "未知歌手",
    album: it.album || "",
    artwork: fixUrl(it.imgUrl || it.hdImgUrl || it.pic || ""),
    duration: dur > 0 ? dur : undefined,
    url: playUrl,
    rid: rid,
  };
}

function mapList(arr) {
  var out = [];
  for (var i = 0; i < arr.length; i++) {
    var x = toItem(arr[i]);
    if (x) out.push(x);
  }
  return out;
}

// 按歌手分组
function groupByArtist(list) {
  var map = {};
  for (var i = 0; i < list.length; i++) {
    var a = list[i].artist || "未知歌手";
    if (!map[a]) map[a] = [];
    map[a].push(list[i]);
  }
  return map;
}

// 生成「某歌手」歌单对象（含封面）
function sheetForArtist(artist, songs) {
  return {
    id: encodeURIComponent(artist),
    title: artist + " 精选",
    description: artist + " 相关 " + songs.length + " 首",
    coverImg: makeCover(artist),
    musicList: songs,
  };
}

/* ---------------- 业务接口 ---------------- */

function searchMusic(query, page) {
  var kw = query == null ? "" : String(query);
  var k = kw.toLowerCase();

  function pageOut(all) {
    var start = (Math.max(1, page) - 1) * PAGE_SIZE;
    return {
      isEnd: start + PAGE_SIZE >= all.length,
      data: all.slice(start, start + PAGE_SIZE),
    };
  }

  function localHit(all) {
    if (!k) return all;
    return all.filter(function (m) {
      return (
        (m.title || "").toLowerCase().indexOf(k) >= 0 ||
        (m.artist || "").toLowerCase().indexOf(k) >= 0
      );
    });
  }

  /* [性能] 服务端 /musiclist/search 是实时校验，实测要 10~13s，而 /musiclist 全量只要几十毫秒。
     所以先在本地全量列表里过滤（毫秒级）；本地没命中时才回落到服务端搜索（给足 25s）。 */
  return fetchAll()
    .then(function (all) {
      var hit = localHit(all);
      if (hit.length || !k) return pageOut(hit);
      return r1Get("/musiclist/search?keyword=" + encodeURIComponent(kw), 25000)
        .then(function (json) {
          var remote = mapList(extractList(json));
          return pageOut(remote.length ? remote : hit);
        })
        .catch(function () {
          return pageOut(hit);
        });
    })
    .catch(function () {
      return { isEnd: true, data: [] };
    });
}

/* ---------------- 导出：MusicFree 插件协议 ---------------- */

return {
  platform: PLATFORM,
  version: "1.2.0",
  author: "本地部署",
  appVersion: ">0.1.0-alpha.0",
  srcUrl: "",
  cacheControl: "no-cache",
  description:
    "对接自建 R1 音乐服务。排行榜/热门歌单按歌手分组；搜索优先在本地全量列表过滤（毫秒级），未命中才回落服务端实时校验。",
  primaryKey: ["id"],
  hints: { importMusicSheet: [] },
  userVariables: [
    {
      key: "baseUrl",
      name: "服务器地址（外网）",
      default: DEFAULT_BASE,
    },
    {
      key: "localBase",
      name: "备用地址（内网，可留空）",
      default: LOCAL_BASE,
    },
  ],
  supportedSearchType: ["music"],

  search: function (query, page, type) {
    return searchMusic(query, page);
  },

  getMediaSource: function (musicItem) {
    // 有 rid 就用「当前连通的 base」现拼播放地址，避免拿缓存里的旧域名
    var rid = musicItem && musicItem.rid;
    var url = rid
      ? getBase() + "/play/" + rid
      : fixUrl(musicItem && musicItem.url);
    return Promise.resolve({ url: fixUrl(url) });
  },

  getMusicUrl: function (musicItem) {
    return this.getMediaSource(musicItem);
  },

  /* 排行榜：按歌手生成多个歌单 */
  getTopLists: function () {
    return fetchAll().then(function (list) {
      var map = groupByArtist(list);
      var data = [];
      Object.keys(map).forEach(function (a) {
        data.push({
          id: encodeURIComponent(a),
          title: a + " 精选",
          description: a + " 相关 " + map[a].length + " 首",
          coverImg: makeCover(a),
        });
      });
      return [{ title: "我的音乐", data: data }];
    });
  },

  // 对齐官方写法：返回「榜单对象 + musicList」，而非 {isEnd,musicList}
  getTopListDetail: function (topListItem) {
    var id = topListItem && topListItem.id;
    var artist = id ? decodeURIComponent(id) : "";
    return fetchAll().then(function (list) {
      var songs = artist
        ? list.filter(function (m) {
            return (m.artist || "未知歌手") === artist;
          })
        : list;
      return assignObj({}, topListItem, { isEnd: true, musicList: songs });
    });
  },

  /* 热门歌单：同样按歌手分组 */
  getRecommendSheetTags: function () {
    return Promise.resolve([
      { title: "R1", data: [{ id: "artist", title: "按歌手" }] },
    ]);
  },

  getRecommendSheetsByTag: function (tag, page) {
    return fetchAll().then(function (list) {
      var map = groupByArtist(list);
      var data = [];
      Object.keys(map).forEach(function (a) {
        data.push({
          id: encodeURIComponent(a),
          title: a + " 精选",
          description: a + " 相关 " + map[a].length + " 首",
          coverImg: makeCover(a),
          artwork: makeCover(a),
        });
      });
      return { isEnd: true, data: data };
    });
  },

  getRecommendSheetDetail: function (sheetItem) {
    var id = sheetItem && sheetItem.id;
    var artist = id ? decodeURIComponent(id) : "";
    return fetchAll().then(function (list) {
      var songs = artist
        ? list.filter(function (m) {
            return (m.artist || "未知歌手") === artist;
          })
        : list;
      return assignObj({}, sheetItem, { isEnd: true, musicList: songs });
    });
  },
};

}

/* ===================== 聚合层 ===================== */
function assignObj(t) {
  for (var i = 1; i < arguments.length; i++) {
    var s = arguments[i];
    if (s) for (var k in s) t[k] = s[k];
  }
  return t;
}
function tag(list, src) {
  return (Array.isArray(list) ? list : []).map(function (x) {
    return assignObj({}, x, { source: src });
  });
}
/* 兼容「直接返回数组」和「返回 {data:[...]}」两种子源写法 */
function asArr(r) {
  if (Array.isArray(r)) return r;
  if (r && Array.isArray(r.data)) return r.data;
  return [];
}
/* 把某个子源方法包成 Promise 并保证拿到数组，异常一律降级为空数组 */
function callArr(ctx, fn, args) {
  return Promise.resolve()
    .then(function () { return fn.apply(ctx, args || []); })
    .then(asArr)
    .catch(function () { return []; });
}
/* [性能] 给慢源加「软超时」：超时先放弃，页面不跟着卡；底层请求继续跑，结果仍会进缓存 */
function withDeadline(p, ms, fallback) {
  if (typeof setTimeout !== "function") return p;
  return new Promise(function (resolve) {
    var done = false;
    var timer = setTimeout(function () {
      if (done) return;
      done = true;
      resolve(fallback);
    }, ms);
    function finish(v) {
      if (done) return;
      done = true;
      try { clearTimeout(timer); } catch (e) {}
      resolve(v);
    }
    p.then(finish, function () { finish(fallback); });
  });
}
/* ===== 子源: buildQQ (QQ音乐，源自 lukaizj/musicfree-plugins，已本地化修复) ===== */
function buildQQ() {

const axios = require("axios");

const PAGE_SIZE = 20;

// Kuwo fallback for tracks if CDN proxy fails
async function kuwoFallback(title, artist) {
    try {
        const query = `${title || ""} ${artist || ""}`.trim();
        const searchUrl = `http://search.kuwo.cn/r.s?rformat=json&encoding=utf8&ft=music&rn=8&pn=0&all=${encodeURIComponent(query)}&itemset=web_2013&client=kt&pcjson=1`;
        const res = await axios.get(searchUrl, {
            headers: { "User-Agent": "okhttp/4.10.0" },
            timeout: 4000
        });
        const abslist = res.data?.abslist || [];
        for (const item of abslist) {
            const rawRid = item.MUSICRID || "";
            const rid = rawRid.split("_")[1]?.split("&")[0] || rawRid.split("_")[0];
            if (!rid) continue;
            const mobiUrl = `http://nmobi.kuwo.cn/mobi.s?f=web&user=0&type=convert_url_with_sign&rid=${rid}&br=128kmp3`;
            const mobiRes = await axios.get(mobiUrl, {
                headers: { "User-Agent": "okhttp/4.10.0" },
                timeout: 4000
            });
            const pUrl = mobiRes.data?.data?.url;
            if (pUrl && pUrl.startsWith("http")) {
                return pUrl;
            }
        }
    } catch (e) {}
    return null;
}

function formatMusicItem(item) {
    const songmid = item.songmid || item.mid || item.id;
    const albummid = item.albummid || item.album?.mid;
    return {
        id: songmid,
        songmid: songmid,
        title: item.songname || item.title || "",
        artist: Array.isArray(item.singer) ? item.singer.map(s => s.name).join(", ") : (item.artist || ""),
        album: item.albumname || item.album?.title || item.album?.name || "",
        artwork: albummid ? `https://y.gtimg.cn/music/photo_new/T002R300x300M000${albummid}.jpg` : undefined,
        duration: item.interval || item.duration || 0,
        qualities: {
            low: { size: item.size128 },
            standard: { size: item.size320 },
            high: { size: item.sizeflac },
            super: { size: item.sizeflac }
        }
    };
}

function formatAlbumItem(item) {
    return {
        id: item.albumMID || item.albumID,
        title: item.albumName || "",
        artist: item.singerName || "",
        artwork: item.albumPic || (item.albumMID ? `https://y.gtimg.cn/music/photo_new/T002R300x300M000${item.albumMID}.jpg` : undefined),
        date: item.publicTime || "",
        description: item.desc || ""
    };
}

function formatArtistItem(item) {
    return {
        id: item.singerMID || item.singerID,
        name: item.singerName || "",
        avatar: item.singerPic || (item.singerMID ? `https://y.gtimg.cn/music/photo_new/T001R150x150M000${item.singerMID}.jpg` : undefined),
        worksNum: item.songNum || 0
    };
}

async function searchBase(query, page, typeCode) {
    try {
        const url = `https://c.y.qq.com/soso/fcgi-bin/search_for_qq_cp?p=${page || 1}&n=${PAGE_SIZE}&w=${encodeURIComponent(query)}&format=json&t=${typeCode}`;
        const res = await axios.get(url, {
            headers: {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                Referer: "https://y.qq.com"
            },
            timeout: 6000
        });
        return res.data?.data || {};
    } catch (e) {
        return {};
    }
}

async function search(query, page, type) {
    if (type === "music") {
        const data = await searchBase(query, page, 0);
        const songData = data.song || {};
        const list = songData.list || [];
        const total = songData.totalnum || list.length;
        return {
            isEnd: (page * PAGE_SIZE) >= total,
            data: list.map(formatMusicItem)
        };
    } else if (type === "album") {
        const data = await searchBase(query, page, 8);
        const albumData = data.album || {};
        const list = albumData.list || [];
        const total = albumData.totalnum || list.length;
        return {
            isEnd: (page * PAGE_SIZE) >= total,
            data: list.map(formatAlbumItem)
        };
    } else if (type === "artist") {
        const data = await searchBase(query, page, 9);
        const singerData = data.singer || {};
        const list = singerData.list || [];
        const total = singerData.totalnum || list.length;
        return {
            isEnd: (page * PAGE_SIZE) >= total,
            data: list.map(formatArtistItem)
        };
    }
    return { isEnd: true, data: [] };
}

async function getMediaSource(musicItem, quality) {
    const songmid = musicItem.songmid || musicItem.id;
    // 1. Try high-speed official CDN proxy (xunhuisi)
    try {
        const apiUrl = `https://api.xunhuisi.store/API/QQMusic/Song.php?mid=${songmid}`;
        const res = await axios.get(apiUrl, {
            headers: { "User-Agent": "Mozilla/5.0" },
            timeout: 4500
        });
        if (res.data && res.data.code === 200 && res.data.music_url) {
            return {
                url: res.data.music_url,
                headers: {
                    Referer: "https://y.qq.com/",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                }
            };
        }
    } catch (e) {}

    // 2. Kuwo fallback
    const fallbackUrl = await kuwoFallback(musicItem.title, musicItem.artist);
    if (fallbackUrl) {
        return { url: fallbackUrl };
    }

    return null;
}

async function getLyric(musicItem) {
    const songmid = musicItem.songmid || musicItem.id;
    try {
        const url = `https://c.y.qq.com/lyric/fcgi-bin/fcg_query_lyric_new.fcg?songmid=${songmid}&format=json&nobase64=1`;
        const res = await axios.get(url, {
            headers: {
                "User-Agent": "Mozilla/5.0",
                Referer: "https://y.qq.com"
            },
            timeout: 4000
        });
        return {
            rawLrc: res.data?.lyric || "",
            translation: res.data?.trans || ""
        };
    } catch (e) {
        return { rawLrc: "" };
    }
}

// 排行榜列表
async function getTopLists() {
    try {
        const res = await axios.get("https://u.y.qq.com/cgi-bin/musicu.fcg?data=%7B%22comm%22%3A%7B%22cv%22%3A4747474%2C%22ct%22%3A24%7D%2C%22toplist%22%3A%7B%22module%22%3A%22musicToplist.ToplistInfoServer%22%2C%22method%22%3A%22GetAll%22%2C%22param%22%3A%7B%7D%7D%7D", {
            headers: { Referer: "https://y.qq.com" }
        });
        const groups = res.data?.toplist?.data?.group || [];
        const result = [];
        const defaultNames = ["官方榜", "地区榜", "特色榜", "全球榜"];
        for (let i = 0; i < groups.length; i++) {
            const g = groups[i];
            const title = g.group_name || defaultNames[i] || "排行榜";
            const data = (g.toplist || []).map(item => ({
                id: item.topId,
                title: item.title,
                description: item.intro,
                coverImg: item.frontPicUrl || item.headPicUrl,
                period: item.period
            }));
            if (data.length) {
                result.push({ title, data });
            }
        }
        return result;
    } catch (e) {
        return [];
    }
}

// 排行榜详情歌曲
async function getTopListDetail(topListItem) {
    try {
        const res = await axios.get(`https://u.y.qq.com/cgi-bin/musicu.fcg?g_tk=5381&data=%7B%22detail%22%3A%7B%22module%22%3A%22musicToplist.ToplistInfoServer%22%2C%22method%22%3A%22GetDetail%22%2C%22param%22%3A%7B%22topId%22%3A${topListItem.id}%2C%22offset%22%3A0%2C%22num%22%3A100%2C%22period%22%3A%22${topListItem.period || ""}%22%7D%7D%2C%22comm%22%3A%7B%22ct%22%3A24%2C%22cv%22%3A0%7D%7D`, {
            headers: { Referer: "https://y.qq.com" }
        });
        const songInfoList = res.data?.detail?.data?.songInfoList || [];
        return {
            ...topListItem,
            musicList: songInfoList.map(item => ({
                id: item.mid || item.id,
                songmid: item.mid,
                title: item.title || item.name,
                artist: (item.singer || []).map(s => s.name).join(", "),
                album: item.album?.title || item.album?.name || "",
                artwork: item.album?.mid ? `https://y.gtimg.cn/music/photo_new/T002R300x300M000${item.album.mid}.jpg` : undefined,
                duration: item.interval || 0
            }))
        };
    } catch (e) {
        return { ...topListItem, musicList: [] };
    }
}

// 热门歌单标签分类
async function getRecommendSheetTags() {
    try {
        const res = (await axios.get("https://c.y.qq.com/splcloud/fcgi-bin/fcg_get_diss_tag_conf.fcg?format=json&inCharset=utf8&outCharset=utf-8", {
            headers: { Referer: "https://y.qq.com/" }
        })).data.data.categories;
        const data = res.slice(1).map((_) => ({
            title: _.categoryGroupName,
            data: _.items.map((tag) => ({
                id: String(tag.categoryId),
                title: tag.categoryName,
            })),
        }));
        return {
            pinned: [
                { id: "10000000", title: "全部" },
                { id: "3317", title: "官方歌单" },
                { id: "71", title: "流行" }
            ],
            data
        };
    } catch (e) {
        return { pinned: [{ id: "10000000", title: "全部" }], data: [] };
    }
}

// 按标签获取热门歌单
async function getRecommendSheetsByTag(tag, page = 1) {
    try {
        const pageSize = 20;
        const categoryId = tag?.id || "10000000";
        const sin = (page - 1) * pageSize;
        const ein = page * pageSize - 1;
        const res = (await axios.get("https://c.y.qq.com/splcloud/fcgi-bin/fcg_get_diss_by_tag.fcg", {
            headers: { Referer: "https://y.qq.com/" },
            params: {
                inCharset: "utf8",
                outCharset: "utf-8",
                sortId: 5,
                categoryId: categoryId,
                sin: sin,
                ein: ein,
                format: "json"
            }
        })).data;
        const list = res?.data?.list || [];
        return {
            isEnd: (res?.data?.sum || 0) <= page * pageSize,
            data: list.map(item => ({
                id: String(item.dissid),
                title: item.dissname,
                artwork: item.imgurl,
                playCount: item.listennum,
                artist: item.creator?.name
            }))
        };
    } catch (e) {
        return { isEnd: true, data: [] };
    }
}

// 歌单详情解析
async function importMusicSheet(urlLike) {
    let id;
    if (typeof urlLike === "string" || typeof urlLike === "number") {
        const str = String(urlLike);
        id = (str.match(/id=([0-9]+)/) || [])[1] || (str.match(/playlist\/([0-9]+)/) || [])[1] || (str.match(/^(\d+)$/) || [])[1];
    } else if (urlLike?.id) {
        id = urlLike.id;
    }
    if (!id) return [];
    try {
        const res = await axios.get(`https://c.y.qq.com/qzone/fcg-bin/fcg_ucc_getcdinfo_byids_cp.fcg?type=1&json=1&utf8=1&onlysong=0&disstid=${id}&format=json`, {
            headers: { Referer: "https://y.qq.com/" }
        });
        const songlist = res.data?.cdlist?.[0]?.songlist || [];
        return songlist.map(formatMusicItem);
    } catch (e) {
        return [];
    }
}

async function getMusicSheetInfo(sheet, page = 1) {
    const list = await importMusicSheet(sheet.id || sheet);
    return {
        isEnd: true,
        musicList: list
    };
}

return {
    platform: "QQ音乐",
    version: "1.1.0",
    primaryKey: ["id", "songmid"],
    cacheControl: "no-cache",
    hints: {
        importMusicSheet: [
            "QQ音乐APP：自建歌单-分享-分享到微信好友/QQ好友；然后点开并复制链接，直接粘贴即可"
        ]
    },
    supportedSearchType: ["music", "album", "artist"],
    search,
    getMediaSource,
    getLyric,
    getTopLists,
    getTopListDetail,
    getRecommendSheetTags,
    getRecommendSheetsByTag,
    importMusicSheet,
    getMusicSheetInfo
};
}

/* ===== 子源: buildNetease (网易云音乐，源自 lukaizj/musicfree-plugins，已本地化修复) ===== */
function buildNetease() {

const axios = require("axios");
const qs = { stringify: function (o) { return Object.keys(o).map(function (k) { return encodeURIComponent(k) + "=" + encodeURIComponent(o[k]); }).join("&"); } };

const PAGE_SIZE = 20;

// Kuwo fallback for grey/VIP tracks
async function kuwoFallback(title, artist) {
    try {
        const query = `${title || ""} ${artist || ""}`.trim();
        const searchUrl = `http://search.kuwo.cn/r.s?rformat=json&encoding=utf8&ft=music&rn=8&pn=0&all=${encodeURIComponent(query)}&itemset=web_2013&client=kt&pcjson=1`;
        const res = await axios.get(searchUrl, {
            headers: { "User-Agent": "okhttp/4.10.0" },
            timeout: 4000
        });
        const abslist = res.data?.abslist || [];
        for (const item of abslist) {
            const rawRid = item.MUSICRID || "";
            const rid = rawRid.split("_")[1]?.split("&")[0] || rawRid.split("_")[0];
            if (!rid) continue;
            const mobiUrl = `http://nmobi.kuwo.cn/mobi.s?f=web&user=0&type=convert_url_with_sign&rid=${rid}&br=128kmp3`;
            const mobiRes = await axios.get(mobiUrl, {
                headers: { "User-Agent": "okhttp/4.10.0" },
                timeout: 4000
            });
            const pUrl = mobiRes.data?.data?.url;
            if (pUrl && pUrl.startsWith("http")) {
                return pUrl;
            }
        }
    } catch (e) {}
    return null;
}

function formatMusicItem(item) {
    const album = item.album || item.al || {};
    const artists = item.artists || item.ar || [];
    const artwork = album.picUrl || (album.picId ? `https://p1.music.126.net/${album.picId}/${album.picId}.jpg` : (artists[0]?.img1v1Url || undefined));
    return {
        id: item.id,
        title: item.name || "",
        artist: artists.map(a => a.name).join(", "),
        album: album.name || "",
        artwork: artwork,
        duration: Math.round((item.duration || 0) / 1000),
        qualities: {
            low: { size: item.l?.size },
            standard: { size: item.m?.size },
            high: { size: item.h?.size },
            super: { size: item.sq?.size }
        }
    };
}

function formatAlbumItem(item) {
    const artist = item.artist || (item.artists && item.artists[0]) || {};
    return {
        id: item.id,
        title: item.name || "",
        artist: artist.name || "",
        artwork: item.picUrl || undefined,
        date: item.publishTime ? new Date(item.publishTime).toLocaleDateString() : "",
        description: item.description || ""
    };
}

function formatArtistItem(item) {
    return {
        id: item.id,
        name: item.name || "",
        avatar: item.picUrl || item.img1v1Url || undefined,
        worksNum: item.musicSize || 0
    };
}

async function search(query, page, type) {
    let nType = 1;
    if (type === "album") nType = 10;
    else if (type === "artist") nType = 100;
    else if (type !== "music") return { isEnd: true, data: [] };

    try {
        const url = "https://music.163.com/api/search/get/web";
        const postData = qs.stringify({
            s: query,
            type: nType,
            offset: ((page || 1) - 1) * PAGE_SIZE,
            limit: PAGE_SIZE,
            total: true
        });
        const res = await axios.post(url, postData, {
            headers: {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                Referer: "https://music.163.com",
                Cookie: "os=pc;",
                "Content-Type": "application/x-www-form-urlencoded"
            },
            timeout: 6000
        });
        const result = res.data?.result || {};
        if (type === "music") {
            const songs = result.songs || [];
            const count = result.songCount || songs.length;
            return {
                isEnd: (page * PAGE_SIZE) >= count,
                data: songs.map(formatMusicItem)
            };
        } else if (type === "album") {
            const albums = result.albums || [];
            const count = result.albumCount || albums.length;
            return {
                isEnd: (page * PAGE_SIZE) >= count,
                data: albums.map(formatAlbumItem)
            };
        } else if (type === "artist") {
            const artists = result.artists || [];
            const count = result.artistCount || artists.length;
            return {
                isEnd: (page * PAGE_SIZE) >= count,
                data: artists.map(formatArtistItem)
            };
        }
    } catch (err) {
        return { isEnd: true, data: [] };
    }
    return { isEnd: true, data: [] };
}

async function getMediaSource(musicItem, quality) {
    // 1. Try oiapi
    try {
        const oiUrl = `http://oiapi.net/API/Music_163?id=${musicItem.id}`;
        const res = await axios.get(oiUrl, {
            headers: { "User-Agent": "Mozilla/5.0" },
            timeout: 4500
        });
        const url = res.data?.data?.[0]?.url;
        if (url && url.startsWith("http")) {
            return { url };
        }
    } catch (e) {}

    // 2. Try official outer url (free songs)
    try {
        const outerUrl = `https://music.163.com/song/media/outer/url?id=${musicItem.id}.mp3`;
        const testRes = await axios.head(outerUrl, {
            headers: { "User-Agent": "Mozilla/5.0" },
            maxRedirects: 3,
            timeout: 3000
        });
        if (testRes.status === 200) {
            return { url: outerUrl };
        }
    } catch (e) {}

    // 3. Fallback to Kuwo
    const fallbackUrl = await kuwoFallback(musicItem.title, musicItem.artist);
    if (fallbackUrl) {
        return { url: fallbackUrl };
    }

    return null;
}

async function getLyric(musicItem) {
    try {
        const url = `https://music.163.com/api/song/lyric?id=${musicItem.id}&lv=1&tv=1`;
        const res = await axios.get(url, {
            headers: {
                "User-Agent": "Mozilla/5.0",
                Referer: "https://music.163.com"
            },
            timeout: 4000
        });
        return {
            rawLrc: res.data?.lrc?.lyric || "",
            translation: res.data?.tlyric?.lyric || ""
        };
    } catch (e) {
        return { rawLrc: "" };
    }
}

// 排行榜列表
async function getTopLists() {
    try {
        const res = await axios.get("https://music.163.com/api/toplist", {
            headers: { "User-Agent": "Mozilla/5.0" }
        });
        const list = res.data?.list || [];
        const official = list.slice(0, 4).map(item => ({
            id: item.id,
            title: item.name,
            description: item.description,
            coverImg: item.coverImgUrl,
            period: item.updateFrequency
        }));
        const others = list.slice(4).map(item => ({
            id: item.id,
            title: item.name,
            description: item.description,
            coverImg: item.coverImgUrl,
            period: item.updateFrequency
        }));
        const result = [];
        if (official.length) result.push({ title: "官方榜", data: official });
        if (others.length) result.push({ title: "特色榜单", data: others });
        return result;
    } catch (e) {
        return [];
    }
}

// 排行榜详情
async function getTopListDetail(topListItem) {
    try {
        const res = await axios.get(`https://music.163.com/api/playlist/detail?id=${topListItem.id}`, {
            headers: { "User-Agent": "Mozilla/5.0" }
        });
        const tracks = res.data?.result?.tracks || [];
        return {
            ...topListItem,
            musicList: tracks.map(formatMusicItem)
        };
    } catch (e) {
        return { ...topListItem, musicList: [] };
    }
}

// 热门歌单标签分类
async function getRecommendSheetTags() {
    try {
        const res = await axios.get("https://music.163.com/api/playlist/catalogue", {
            headers: { "User-Agent": "Mozilla/5.0" }
        });
        const categories = res.data?.categories || {};
        const sub = res.data?.sub || [];
        const groups = {};
        for (const [key, name] of Object.entries(categories)) {
            groups[key] = { title: name, data: [] };
        }
        for (const item of sub) {
            if (groups[item.category]) {
                groups[item.category].data.push({
                    id: item.name,
                    title: item.name
                });
            }
        }
        return {
            pinned: [
                { id: "全部", title: "全部" },
                { id: "华语", title: "华语" },
                { id: "流行", title: "流行" },
                { id: "摇滚", title: "摇滚" },
                { id: "民谣", title: "民谣" }
            ],
            data: Object.values(groups)
        };
    } catch (e) {
        return { pinned: [{ id: "全部", title: "全部" }], data: [] };
    }
}

// 按标签获取热门歌单
async function getRecommendSheetsByTag(tag, page = 1) {
    try {
        const pageSize = 20;
        const cat = tag?.id || "全部";
        const offset = (page - 1) * pageSize;
        const res = await axios.get(`https://music.163.com/api/playlist/list?cat=${encodeURIComponent(cat)}&order=hot&offset=${offset}&limit=${pageSize}`, {
            headers: { "User-Agent": "Mozilla/5.0" }
        });
        const playlists = res.data?.playlists || [];
        return {
            isEnd: (res.data?.total || 0) <= page * pageSize,
            data: playlists.map(item => ({
                id: item.id,
                title: item.name,
                artwork: item.coverImgUrl,
                playCount: item.playCount,
                artist: item.creator?.nickname
            }))
        };
    } catch (e) {
        return { isEnd: true, data: [] };
    }
}

// 歌单详情解析
async function importMusicSheet(urlLike) {
    let id;
    if (typeof urlLike === "string" || typeof urlLike === "number") {
        const str = String(urlLike);
        id = (str.match(/id=([0-9]+)/) || [])[1] || (str.match(/playlist\/([0-9]+)/) || [])[1] || (str.match(/^(\d+)$/) || [])[1];
    } else if (urlLike?.id) {
        id = urlLike.id;
    }
    if (!id) return [];
    try {
        const res = await axios.get(`https://music.163.com/api/playlist/detail?id=${id}`, {
            headers: { "User-Agent": "Mozilla/5.0" }
        });
        const tracks = res.data?.result?.tracks || [];
        return tracks.map(formatMusicItem);
    } catch (e) {
        return [];
    }
}

async function getMusicSheetInfo(sheet, page = 1) {
    const list = await importMusicSheet(sheet.id || sheet);
    return {
        isEnd: true,
        musicList: list
    };
}

return {
    platform: "网易云音乐",
    version: "1.1.0",
    primaryKey: ["id"],
    cacheControl: "no-cache",
    hints: {
        importMusicSheet: [
            "网易云音乐APP：歌单-分享-复制链接，直接粘贴即可"
        ]
    },
    supportedSearchType: ["music", "album", "artist"],
    search,
    getMediaSource,
    getLyric,
    getTopLists,
    getTopListDetail,
    getRecommendSheetTags,
    getRecommendSheetsByTag,
    importMusicSheet,
    getMusicSheetInfo
};
}

var R1 = buildR1();
var BILI = buildBili();
var MAO = buildMao();
var QQ = buildQQ();
var NE = buildNetease();

var SRC = { r1: R1, bili: BILI, mao: MAO, qq: QQ, ne: NE };
var LABEL = { r1: "R1本地", bili: "B站", mao: "猫耳", qq: "QQ", ne: "网易云" };
var ORDER = ["r1", "bili", "qq", "ne", "mao"];

function srcOf(obj, fallback) {
  if (obj && obj.source && SRC[obj.source]) return obj.source;
  if (obj && obj.data && obj.data[0] && SRC[obj.data[0].source]) return obj.data[0].source;
  return fallback || "r1";
}

/* 按 source 顺序逐个试，返回第一个能拿到 url 的结果 */
function tryMedia(m, first) {
  var order = [first].concat(ORDER).filter(function (k, i, a) {
    return k && SRC[k] && a.indexOf(k) === i;
  });
  var i = 0;
  function next() {
    if (i >= order.length) return { url: "" };
    var k = order[i++];
    return Promise.resolve()
      .then(function () { return SRC[k].getMediaSource(m); })
      .then(function (r) {
        var u = r && (typeof r === "string" ? r : r.url);
        return u ? r : next();
      })
      .catch(function () { return next(); });
  }
  return Promise.resolve().then(next);
}

/* [性能] 排行榜/歌单标签短缓存：频繁切页时不重复打网络 */
var TOP_CACHE = { at: 0, data: null };
var TOP_TTL = 120 * 1000;
var MARK_TIMEOUT = { timeout: true };

module.exports = {
  platform: "R1音乐+",
  version: "2.3.2",
  author: "本地部署",
  appVersion: ">0.1.0-alpha.0",
  srcUrl: "",
  cacheControl: "no-cache",
  description:
    "聚合音源：R1 本地音乐 + B站音频 + QQ音乐 + 网易云 + 猫耳FM。搜索合并；排行榜/热门歌单按源分列（标题带【来源】前缀）；靠 source 字段分发。",
  primaryKey: ["id"],
  hints: { importMusicSheet: [] },
  userVariables: R1.userVariables,
  supportedSearchType: ["music"],

  search: function (query, page, type) {
    function one(src) {
      var ctx = SRC[src];
      var p = Promise.resolve()
        .then(function () { return ctx.search(query, page, type); })
        .then(function (r) {
          return { isEnd: !!(r && r.isEnd), data: tag(r && r.data, src) };
        })
        .catch(function () { return { isEnd: true, data: [] }; });
      // R1 服务端实时校验可能十几秒，软超时 6s 先出其他源的结果
      if (src === "r1") return withDeadline(p, 6000, { isEnd: true, data: [] });
      return p;
    }
    return Promise.all(ORDER.map(one)).then(function (res) {
      var data = [];
      var isEnd = true;
      res.forEach(function (r) { data = data.concat(r.data); isEnd = isEnd && r.isEnd; });
      return { isEnd: isEnd, data: data };
    });
  },

  getMediaSource: function (m) {
    return tryMedia(m, (m && m.source) || "r1");
  },
  getMusicUrl: function (m) { return this.getMediaSource(m); },

  getLyric: function (m) {
    var src = srcOf(m, "r1");
    var p = SRC[src];
    if (!p || typeof p.getLyric !== "function") return Promise.resolve({ rawLrc: "" });
    return Promise.resolve()
      .then(function () { return p.getLyric(m); })
      .catch(function () { return { rawLrc: "" }; });
  },

  /* 排行榜：每个源的榜单**分列列出**，标题统一加【来源】前缀 */
  getTopLists: function () {
    var now = Date.now();
    if (TOP_CACHE.data && now - TOP_CACHE.at < (TOP_CACHE.ttl || TOP_TTL))
      return Promise.resolve(TOP_CACHE.data);

    var sources = ["r1", "bili", "qq", "ne"];
    var r1Pending = false;
    return Promise.all(sources.map(function (s) {
      var p = callArr(SRC[s], SRC[s].getTopLists);
      // R1（自建服务）偶尔很慢，给它 2.5s 软超时：先出其他源，R1 稍后自然进缓存
      if (s !== "r1") return p;
      return withDeadline(p, 2500, MARK_TIMEOUT).then(function (v) {
        if (v === MARK_TIMEOUT) { r1Pending = true; return []; }
        return v;
      });
    })).then(function (res) {
      var groups = [];
      res.forEach(function (arr, i) {
        var src = sources[i];
        arr.forEach(function (g) {
          if (!g) return;
          var data = tag(g.data, src);
          if (!data.length) return; // 空分组点进去一片空白，直接丢弃
          groups.push(assignObj({}, g, {
            source: src,
            title: "【" + LABEL[src] + "】" + (g.title || "排行榜"),
            data: data,
          }));
        });
      });
      // R1 没赶上：仍给 15s 短缓存，避免每次切页都白等 2.5s；R1 结果由下次刷新补上
      TOP_CACHE = { at: Date.now(), data: groups, ttl: r1Pending ? 15 * 1000 : TOP_TTL };
      return groups;
    });
  },

  getTopListDetail: function (tl, page) {
    var src = srcOf(tl, "r1");
    var p = SRC[src];
    var fn = p.getTopListDetail || p.getMusicSheetInfo;
    return Promise.resolve()
      .then(function () { return fn.call(p, tl, page); })
      .then(function (r) {
        var out = assignObj({}, tl, r || {});
        out.source = src;
        out.isEnd = r && typeof r.isEnd === "boolean" ? r.isEnd : true;
        out.musicList = tag(r && r.musicList, src);
        return out;
      })
      .catch(function () {
        return assignObj({}, tl, { source: src, isEnd: true, musicList: [] });
      });
  },

  /* 热门歌单：同样按源分列 */
  getRecommendSheetTags: function () {
    var sources = ["r1", "qq", "ne", "mao"];
    return Promise.all(sources.map(function (s) {
      var p = callArr(SRC[s], SRC[s].getRecommendSheetTags);
      if (s !== "r1") return p;
      return withDeadline(p, 2500, []);
    })).then(function (res) {
      var out = [];
      res.forEach(function (arr, i) {
        var src = sources[i];
        arr.forEach(function (t) {
          if (!t) return;
          var data = tag(t.data, src);
          if (!data.length) return;
          out.push(assignObj({}, t, {
            source: src,
            title: "【" + LABEL[src] + "】" + (t.title || "歌单"),
            data: data,
          }));
        });
      });
      return out;
    });
  },

  getRecommendSheetsByTag: function (t, page) {
    var src = srcOf(t, "r1");
    var p = SRC[src];
    var fn = p.getRecommendSheetsByTag || p.getMusicSheetInfo;
    return Promise.resolve()
      .then(function () { return fn.call(p, t, page); })
      .then(function (r) {
        if (Array.isArray(r)) return { isEnd: true, data: tag(r, src) };
        return {
          isEnd: r && typeof r.isEnd === "boolean" ? r.isEnd : true,
          data: tag(r && r.data, src),
        };
      })
      .catch(function () { return { isEnd: true, data: [] }; });
  },

  getRecommendSheetDetail: function (sheet, page) {
    var src = srcOf(sheet, "r1");
    var p = SRC[src];
    var fn = p.getRecommendSheetDetail || p.getMusicSheetInfo;
    return Promise.resolve()
      .then(function () { return fn.call(p, sheet, page); })
      .then(function (r) {
        var out = assignObj({}, sheet, r || {});
        out.source = src;
        out.isEnd = r && typeof r.isEnd === "boolean" ? r.isEnd : true;
        out.musicList = tag(r && r.musicList, src);
        return out;
      })
      .catch(function () {
        return assignObj({}, sheet, { source: src, isEnd: true, musicList: [] });
      });
  },

  getMusicSheetInfo: function (sheet, page) {
    return this.getRecommendSheetDetail(sheet, page);
  },

  importMusicSheet: function (urlLike) {
    var p = SRC.qq;
    if (p && typeof p.importMusicSheet === "function") {
      return Promise.resolve()
        .then(function () { return p.importMusicSheet(urlLike); })
        .catch(function () { return []; });
    }
    return [];
  },
};
