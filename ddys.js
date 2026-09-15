/*
 * 嘀嗒影视 (didahd.xyz) TVBox / FYT 源
 * 站点内核：苹果CMS MYUI 模板
 * 分类：/type/N.html（分页走 /show/N--------P---.html）
 * 详情：/detail/N.html    播放：/play/N-S-E.html
 * 搜索：/search/关键词----------P---.html
 * 说明：本站的播放地址是「夸克网盘分享链接」(pan.quark.cn/s/...)，
 *       需 TVBox / FYT 已配置夸克网盘解析器才能正常播放。
 */
var rule = {
    title: '嘀嗒影视',
    host: 'https://www.didahd.xyz',
    homeUrl: '',
    // 分类列表：fyclass=类型ID，fypage=页码（/show/1--------1---.html）
    url: '/show/fyclass--------fypage---.html',
    // 搜索：关键词 + 翻页
    searchUrl: '/search/**----------fypage---.html',
    searchable: 2,
    quickSearch: 0,
    filterable: 0,
    headers: {
        'User-Agent': 'MOBILE_UA'
    },
    timeout: 5000,
    // 从顶部导航抓取分类（跳过「首页」，取其后 5 个类型：电影/电视剧/纪录片/动漫/综艺）
    class_parse: '.myui-header__menu li.hidden-sm.hidden-xs:gt(0):lt(5);a&&Text;a&&href;/(\\d+).html',
    play_parse: true,
    // 播放页 player_xxxx JSON 中的 url 字段即真实播放地址（夸克网盘分享链）
    lazy: 'js:let html=fetch(input,fetch_params);let m=html.match(/var player_\\w+=\\{[\\s\\S]*?\"url\"\\s*:\\s*\"([^\"]+)\"/);input=m?m[1]:input;',
    double: true,
    limit: 6,
    // 首页推荐（首页卡片用 img src 取图）
    推荐: 'ul.myui-vodlist.clearfix;li;a&&title;img&&src;.pic-text&&Text;a&&href',
    // 一级列表（分类/搜索结果页，卡片封面用 data-original）
    一级: '.myui-vodlist li;a&&title;a&&data-original;.pic-text&&Text;a&&href',
    // 二级详情
    二级: {
        "title": ".myui-content__detail .title&&Text",
        "img": ".myui-content__thumb .lazyload&&data-original",
        "desc": ".myui-content__detail p:eq(0)&&Text;.myui-content__detail p:eq(1)&&Text;.myui-content__detail p:eq(2)&&Text",
        "content": ".myui-content__detail .content&&Text",
        "tabs": ".nav-tabs:eq(0) li",
        "lists": ".myui-content__list:eq(#id) li"
    },
    // 搜索结果（#searchList li，封面用 data-original）
    搜索: '#searchList li;a&&title;a&&data-original;.pic-text&&Text;a&&href'
}
