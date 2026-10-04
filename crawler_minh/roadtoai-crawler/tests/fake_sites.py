from __future__ import annotations

import asyncio
import socket
import threading

from aiohttp import web

VI_PARAGRAPHS = [
    "Sỏi thận là bệnh lý thường gặp của hệ tiết niệu, gây đau quặn thận, tiểu máu và có thể dẫn tới tắc nghẽn đường tiết niệu.",
    "Khi sỏi gây tắc nghẽn kèm nhiễm khuẩn, người bệnh cần được giải áp sớm bằng đặt thông niệu quản hoặc dẫn lưu thận qua da.",
    "Uống đủ nước, hạn chế muối và đạm động vật giúp giảm nguy cơ tái phát sỏi sau điều trị.",
]
EN_PARAGRAPHS = [
    "Kidney stones are hard deposits of minerals and salts that form inside the kidneys and can block the urinary tract.",
    "Obstructing stones with signs of infection require urgent decompression with a ureteral stent or percutaneous nephrostomy.",
    "Drinking enough water and limiting salt intake lowers the risk of recurrence after treatment.",
]
ZH_PARAGRAPHS = [
    "肾结石是泌尿系统的常见疾病，可引起肾绞痛、血尿，并可能导致尿路梗阻。",
    "当结石合并感染并造成梗阻时，应尽早通过输尿管支架或经皮肾造瘘进行引流减压。",
    "多饮水、限制盐分摄入有助于降低治疗后结石复发的风险。",
]


DUP_ARTICLE = [
    "Tăng huyết áp là bệnh mạn tính thường gặp, cần theo dõi huyết áp tại nhà và tái khám định kỳ theo hẹn của bác sĩ.",
    "Người bệnh nên ăn nhạt, hạn chế rượu bia, tập thể dục đều đặn và uống thuốc đúng liều, không tự ý ngưng thuốc.",
]
GONE_NOTICE = "抱歉，您访问的页面不存在或已被删除，请返回首页继续浏览其他健康资讯，或使用站内搜索查找相关内容。"
OLD_ZH_ARTICLE = "俄罗斯一位专家提出了男性健康的标准，即四快：吃得快、便得快、睡得快、说得快。所谓吃得快，是指吃饭时不挑食，吃得香甜。"


def minimal_pdf(text: str) -> bytes:
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("latin-1")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def page_html(title: str, paragraphs: list[str], charset: str = "utf-8", nav: str = "Trang chủ | Tin tức | Liên hệ") -> str:
    body = "".join(f"<p>{p}</p>" for p in paragraphs)
    return (f"<html><head><meta charset=\"{charset}\"><title>{title}</title>"
            f"<meta property=\"article:published_time\" content=\"2024-03-05T08:00:00+07:00\">"
            f"<script>var tracking = 1;</script><style>p{{color:#333}}</style></head>"
            f"<body><nav>{nav}</nav><article><h1>{title}</h1>{body}</article>"
            f"<footer>2026</footer></body></html>")


def make_app(profile: str) -> web.Application:
    limited_seen: set[str] = set()
    robots_hits = [0]

    async def robots(request: web.Request) -> web.StreamResponse:
        robots_hits[0] += 1
        if profile == "flaky":
            if robots_hits[0] <= 4:
                raise web.HTTPServiceUnavailable()
            return web.Response(text="User-agent: *\nAllow: /\n")
        if profile == "vi":
            return web.Response(text="User-agent: *\nDisallow: /private/\n")
        if profile == "zh":
            return web.Response(text="User-agent: *\nCrawl-delay: 0.2\n")
        if profile == "dead":
            raise web.HTTPInternalServerError()
        raise web.HTTPNotFound()

    async def page(request: web.Request) -> web.StreamResponse:
        kind = request.match_info["kind"]
        n = request.match_info["n"]
        if kind == "missing":
            raise web.HTTPNotFound()
        if kind == "blocked":
            raise web.HTTPForbidden()
        if kind == "redirect":
            raise web.HTTPMovedPermanently(location=f"/bai-viet/{n}")
        if kind == "file":
            return web.Response(body=b"\x89PNG\r\n", content_type="image/png")
        if kind == "pdf":
            return web.Response(body=minimal_pdf(f"Huong dan dieu tri soi than so {n}"), content_type="application/pdf")
        if kind == "short":
            return web.Response(text="<html><body><p>Hi</p></body></html>", content_type="text/html")
        if kind == "slow":
            await asyncio.sleep(2.5)
        if kind == "limited" and n not in limited_seen:
            limited_seen.add(n)
            return web.Response(status=429, headers={"Retry-After": "1"})
        if kind == "dup":
            first = DUP_ARTICLE[0].upper() if profile == "en" else DUP_ARTICLE[0]
            gap = "   " if profile == "en" else " "
            paragraphs = [first.replace(" ", gap), *DUP_ARTICLE[1:], f"Bài dùng chung số {n} được nhiều trang đăng lại."]
            return web.Response(text=page_html(f"Bài đăng lại {n}", paragraphs), content_type="text/html")
        if kind == "gone":
            html = page_html("页面不存在", [GONE_NOTICE] * 3, charset="gbk", nav="首页 | 新闻 | 联系我们")
            return web.Response(body=html.encode("gbk"), content_type="text/html")
        if profile == "zh":
            html = page_html(f"第{n}篇 肾结石的治疗", [*ZH_PARAGRAPHS, f"本文编号为{n}，属于泌尿外科专栏。"], charset="gbk",
                             nav="首页 | 新闻 | 联系我们")
            return web.Response(body=html.encode("gbk"), content_type="text/html")
        if profile == "zhold":
            script = "<script>" + ";".join(f"var a{i}=document.getElementById('x{i}');" for i in range(150)) + "</script>"
            style = "<style>" + "".join(f".c{i}{{margin:{i}px;padding:2px}}" for i in range(120)) + "</style>"
            text = chr(0x3000) * 2 + f"第{n}号文章。" + OLD_ZH_ARTICLE * 30
            html = (f"<html><head><title>男性健康的标准 {n}</title>{style}{script}</head><body><div>首页</div>"
                    f"<div class=\"content\"><p>{text}</p><p>&nbsp;&nbsp;&nbsp;</p><p>   回复   </p></div>{script}"
                    f"<div>版权所有</div></body></html>")
            header = "text/html; charset=gb2312" if int(n) % 2 == 0 else "text/html"
            return web.Response(body=html.encode("gbk"), headers={"Content-Type": header})
        if profile == "en":
            paragraphs = [*EN_PARAGRAPHS, f"This is reference article number {n} of the urology section."]
            return web.Response(text=page_html(f"Article {n}: kidney stones", paragraphs), content_type="text/html")
        paragraphs = [*VI_PARAGRAPHS, f"Đây là bài viết số {n} của chuyên mục tiết niệu về sỏi thận."]
        return web.Response(text=page_html(f"Bài viết {n}: sỏi thận", paragraphs), content_type="text/html")

    app = web.Application()
    app.router.add_get("/robots.txt", robots)
    app.router.add_get("/{kind}/{n}", page)
    return app


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def start(profiles: list[str]) -> tuple[dict[str, int], callable]:
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    runners = []

    async def setup() -> dict[str, int]:
        ports = {}
        for profile in profiles:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("127.0.0.1", 0))
            sock.listen(256)
            runner = web.AppRunner(make_app(profile), access_log=None)
            await runner.setup()
            await web.SockSite(runner, sock).start()
            runners.append(runner)
            ports[profile] = sock.getsockname()[1]
        return ports

    ports = asyncio.run_coroutine_threadsafe(setup(), loop).result()

    def stop() -> None:
        async def cleanup() -> None:
            for r in runners:
                await r.cleanup()
        asyncio.run_coroutine_threadsafe(cleanup(), loop).result()
        loop.call_soon_threadsafe(loop.stop)

    return ports, stop
