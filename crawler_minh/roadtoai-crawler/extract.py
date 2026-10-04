from __future__ import annotations

import io
import re
from urllib.parse import urlsplit

MAX_DATA_SCRIPT = 300_000
SHORT_TEXT = 200
_BLOCK_TAGS = {"p", "div", "li", "tr", "td", "th", "h1", "h2", "h3", "h4", "h5", "h6", "dd", "dt", "section", "article",
               "blockquote", "pre", "table", "ul", "ol"}
_HIDDEN = re.compile(r"display\s*:\s*none", re.IGNORECASE)


def _chars(*codes: int) -> str:
    return "".join(chr(c) for c in codes)


_BLOCKS = re.compile(r"<(script|style|noscript|svg)\b[^>]*>.*?</\1\s*>", re.IGNORECASE | re.DOTALL)
_DATA_SCRIPT = re.compile(r"<script\b[^>]*\btype\s*=\s*[\"']?application/(?:ld\+)?json\b", re.IGNORECASE)
_COMMENTS = re.compile(r"<!--.*?-->", re.DOTALL)
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_DMY = re.compile(r"(?<!\d)(\d{1,2})/(\d{1,2})/(\d{4})(?!\d)")
_WHITESPACE = re.compile(r"\s+")

_HEADER_CHARSET = re.compile(r"charset\s*=\s*[\"']?\s*([A-Za-z0-9_\-.:]+)", re.IGNORECASE)
_META_CHARSET = re.compile(rb"<meta[^>]+?charset\s*=\s*[\"']?\s*([A-Za-z0-9_\-.:]+)", re.IGNORECASE)
_XML_ENCODING = re.compile(rb"<\?xml[^>]+?encoding\s*=\s*[\"']([A-Za-z0-9_\-.:]+)", re.IGNORECASE)
_ALIASES = {
    "gb2312": "gb18030", "gbk": "gb18030", "gb_2312-80": "gb18030", "x-gbk": "gb18030", "cp936": "gb18030",
    "936": "gb18030", "x-euc-cn": "gb18030", "euc-cn": "gb18030", "utf8": "utf-8", "unicode": "utf-8",
    "big5": "big5hkscs",
}
_WEAK = {"iso-8859-1", "iso8859-1", "latin-1", "latin1", "windows-1252", "cp1252", "us-ascii", "ascii"}

_CJK = re.compile("[" + chr(0x3400) + "-" + chr(0x4DBF) + chr(0x4E00) + "-" + chr(0x9FFF) + "]")
_COMMON_ZH = set(
    "的一是不了人我在有他这中大来上国个到说们为子和你地出道也时年得就那要下以生会自着去之过家学对可她里后小么心多天而能好都"
    "然没日于起还发成事只作当想看文无开手十用主行方又如前所本见经头面公同三已老从动两长知民样现分将外但身些与高意进把法此实回"
    "二理美点月明其种声全工己话儿者向情部正名定女问力机给等几很业最间新什打便位因重被走电四第门相次东政海口使教西再平真听世气"
    "信北少关并内加化由却代军产入先山五太水万市眼体别处总才场师书比住员九笑性通目华报立马命张活难神数件安表原车白应路期叫死常"
    "提感金何更反合放做系计或司利受光王果亲界及今京务制解各任至清物台象记边共风战干接它许八特觉望直服毛林题建南度统色字请交爱"
    "让认算论百吃义科怎元社术结六功指思非流每青管夫连远资队跟带花快条院变联言权往展该领传近留红治决周保达办运武半候七必城父强"
    "步完革深区即求品士转量空甚众技轻程告江语英基派满式李息写呢识极令黄德收脸钱党倒未持取设始版双历越史商千片容研像找友孩站广"
    "改议形委早房音火际则首单据导影失拿网香似斯专石若兵弟谁校读志飞观争究包组造落视济喜离虽坏病医药症疗患血疼痛肝肺肾胃炎癌"
)
_SPACES = re.compile("[ \t" + _chars(0xA0, *range(0x2000, 0x200B), 0x202F, 0x205F, 0x3000) + "]+")
_ZERO_WIDTH = re.compile("[" + _chars(0x200B, 0x200C, 0x200D, 0xFEFF) + "]")


def _norm_encoding(name: str) -> str:
    n = name.strip().strip("\"'").lower()
    return _ALIASES.get(n, n)


def _try_decode(body: bytes, encoding: str) -> str | None:
    try:
        return body.decode(encoding)
    except (LookupError, UnicodeDecodeError):
        return None


def _looks_chinese(text: str) -> bool:
    cjk = _CJK.findall(text[:20000])
    if len(cjk) < 30:
        return False
    common = sum(1 for c in cjk if c in _COMMON_ZH)
    return common / len(cjk) > 0.15


def decode_html(body: bytes, content_type: str = "") -> tuple[str, str]:
    if body.startswith(b"\xef\xbb\xbf"):
        return body[3:].decode("utf-8", errors="replace"), "utf-8-sig"
    if body[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return body.decode("utf-16", errors="replace"), "utf-16"
    text = _try_decode(body, "utf-8")
    if text is not None:
        return text, "utf-8"

    declared = []
    m = _HEADER_CHARSET.search(content_type or "")
    if m:
        declared.append(_norm_encoding(m.group(1)))
    head = body[:32768]
    for rx in (_META_CHARSET, _XML_ENCODING):
        m = rx.search(head)
        if m:
            declared.append(_norm_encoding(m.group(1).decode("ascii", "ignore")))

    for enc in declared:
        if enc in _WEAK or enc == "utf-8":
            continue
        text = _try_decode(body, enc)
        if text is not None:
            return text, enc

    gb = _try_decode(body, "gb18030")
    if gb is not None and _looks_chinese(gb):
        return gb, "gb18030"

    for enc in declared:
        if enc in _WEAK:
            text = _try_decode(body, enc)
            if text is not None:
                return text, enc

    try:
        from charset_normalizer import from_bytes
        best = from_bytes(body).best()
        if best is not None and best.encoding:
            return body.decode(best.encoding, errors="replace"), best.encoding
    except Exception:
        pass
    return body.decode("utf-8", errors="replace"), "utf-8-replace"


def clean_text(text: str) -> str:
    text = _ZERO_WIDTH.sub("", text.replace("\r\n", "\n").replace("\r", "\n"))
    lines = (_SPACES.sub(" ", line).strip() for line in text.split("\n"))
    return "\n".join(line for line in lines if line)


def _keep_data_scripts(m: re.Match) -> str:
    block = m.group(0)
    if m.group(1).lower() == "script" and len(block) <= MAX_DATA_SCRIPT and _DATA_SCRIPT.match(block):
        return block
    return ""


def slim_html(html: str) -> str:
    return _COMMENTS.sub("", _BLOCKS.sub(_keep_data_scripts, html))


def _safe(text: str) -> str:
    return text.encode("utf-8", errors="ignore").decode("utf-8")


def _norm_date(value) -> str:
    if not value:
        return ""
    m = _DATE.search(str(value))
    return m.group(0) if m else ""


def _extract_pdf(body: bytes, max_pages: int) -> tuple[str, str, str]:
    try:
        from pypdf import PdfReader
    except ImportError:
        return "", "", "pypdf not installed"
    reader = PdfReader(io.BytesIO(body))
    parts = []
    for i, page in enumerate(reader.pages):
        if i >= max_pages:
            break
        parts.append(page.extract_text() or "")
    title = ""
    try:
        if reader.metadata and reader.metadata.title:
            title = str(reader.metadata.title)
    except Exception:
        pass
    return title, "\n".join(parts), ""


def _trafilatura(html: str, url: str, favor_recall: bool) -> tuple[str, str, str]:
    import trafilatura

    doc = trafilatura.bare_extraction(
        html,
        url=url,
        include_comments=False,
        include_tables=True,
        favor_recall=favor_recall,
        with_metadata=True,
    )
    if doc is None:
        return "", "", ""
    if isinstance(doc, dict):
        return doc.get("title") or "", doc.get("text") or "", doc.get("date") or ""
    return getattr(doc, "title", None) or "", getattr(doc, "text", None) or "", getattr(doc, "date", None) or ""


def node_text(node) -> str:
    parts: list[str] = []

    def walk(e) -> None:
        if not isinstance(e.tag, str) or e.tag in ("script", "style", "noscript"):
            return
        if _HIDDEN.search(e.get("style") or ""):
            return
        if e.tag == "br":
            parts.append("\n")
            return
        block = e.tag in _BLOCK_TAGS
        if block:
            parts.append("\n")
        if e.text:
            parts.append(_WHITESPACE.sub(" ", e.text))
        for child in e:
            walk(child)
            if child.tail:
                parts.append(_WHITESPACE.sub(" ", child.tail))
        if block:
            parts.append("\n")

    walk(node)
    return clean_text("".join(parts))


def _site_120ask(tree) -> tuple[str, str, str] | None:
    question = tree.xpath('//*[@id="d_msCon"]')
    if not question:
        return None
    h1 = tree.xpath('//h1[@id="d_askH1"]')
    title = node_text(h1[0]) if h1 else ""
    lines = [title] if title else []
    lines.append(node_text(question[0]))
    for item in tree.xpath('//div[contains(concat(" ", normalize-space(@class), " "), " b_answerli ")]'):
        for body in item.xpath('.//div[contains(@class, "b_anscont_cont")]//div[contains(@class, "crazy_new")]'):
            lines.append(node_text(body))
        for extra in item.xpath('.//div[contains(@class, "b_ansaddli")]'):
            label = "医生回答：" if extra.xpath('.//span[contains(@class, "b_docaddti")]') else "追问："
            said = " ".join(node_text(p) for p in extra.xpath("./p")).strip()
            if said:
                lines.append(label + said)
    for tips in tree.xpath('//div[contains(@class, "sick_cyclopedia")]//div[contains(@class, "cyclopedia_l")]')[:1]:
        lines.append(node_text(tips))
    meta = tree.xpath('//div[contains(@class, "b_askab1")]')
    m = _DATE.search(node_text(meta[0])) if meta else None
    return title, "\n".join(x for x in lines if x), m.group(0) if m else ""


def _dmy(text: str) -> str:
    m = _DMY.search(text)
    if not m:
        return ""
    day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if not (1 <= day <= 31 and 1 <= month <= 12 and 1990 <= year <= 2100):
        return ""
    return f"{year:04d}-{month:02d}-{day:02d}"


def _site_bachmai(tree) -> tuple[str, str, str] | None:
    post = tree.xpath('//*[@id="content-post"]')
    if not post:
        return None
    heading = post[0].xpath("./h3")
    title = node_text(heading[0]) if heading else ""
    lead = "\n".join(node_text(x) for x in post[0].xpath('.//div[contains(@class, "content-excerpt")]'))
    body = "\n".join(node_text(x) for x in post[0].xpath('.//div[contains(@class, "content-editor")]'))
    if lead and " ".join(lead.split()) in " ".join(body.split()):
        lead = ""
    stamps = post[0].xpath('.//*[@id="title-print"]//span | .//div[contains(@class, "post-detail__content-item")]')
    date = next((d for d in (_dmy(node_text(x)) for x in stamps) if d), "")
    return title, "\n".join(x for x in (lead, body) if x), date


SITE_RULES = (
    ("120ask.com", "120ask", _site_120ask),
    ("bachmai.gov.vn", "bachmai", _site_bachmai),
)


def _site_extract(html: str, url: str) -> tuple[str, str, str, str] | None:
    host = (urlsplit(url).hostname or "").lower()
    for suffix, name, rule in SITE_RULES:
        if host == suffix or host.endswith("." + suffix):
            try:
                import lxml.html

                found = rule(lxml.html.fromstring(html))
            except Exception:
                found = None
            if found is not None:
                return _safe(clean_text(found[0])), _safe(clean_text(found[1])), _norm_date(found[2]), "site:" + name
    return None


def extract_html(html: str, url: str) -> tuple[str, str, str, str]:
    site = _site_extract(html, url)
    if site:
        return site
    title, text, date = _trafilatura(html, url, favor_recall=False)
    title, text, extractor = clean_text(title), clean_text(text), "trafilatura"
    if len(text) < SHORT_TEXT:
        title2, text2, date2 = _trafilatura(html, url, favor_recall=True)
        text2 = clean_text(text2)
        if len(text2) > len(text):
            title, text, date, extractor = clean_text(title2) or title, text2, date2 or date, "trafilatura-recall"
    if not text:
        import trafilatura

        text, extractor = clean_text(trafilatura.html2txt(html) or ""), "html2txt"
    return _safe(title), _safe(text), _norm_date(date), extractor if text else ""


def _result(title: str = "", text: str = "", html: bytes = b"", error: str = "", extractor: str = "",
            published_at: str = "") -> dict:
    title, text = _safe(title), _safe(text)
    return {
        "title": title,
        "text": text,
        "html": html,
        "error": error,
        "extractor": extractor if text or extractor.startswith("site:") else "",
        "published_at": published_at,
    }


def extract_document(body: bytes, url: str, kind: str, keep_html: bool, content_type: str = "",
                     max_pdf_pages: int = 300) -> dict:
    html_out = b""
    try:
        if kind == "pdf":
            title, text, err = _extract_pdf(body, max_pdf_pages)
            return _result(clean_text(title), clean_text(text), b"", err, "pypdf")
        decoded, _ = decode_html(body, content_type)
        if kind == "text":
            return _result("", clean_text(decoded), b"", "", "plain")
        decoded = re.sub(r"^\s*<\?xml[^>]*\?>", "", decoded)
        if keep_html:
            html_out = slim_html(decoded).encode("utf-8", errors="replace")
        title, text, date, extractor = extract_html(decoded, url)
        if keep_html and not text and len(decoded) <= MAX_DATA_SCRIPT:
            html_out = decoded.encode("utf-8", errors="replace")
        return _result(title, text, html_out, "", extractor, date)
    except Exception as exc:
        return _result(html=html_out, error=f"{type(exc).__name__}: {exc}"[:300])
