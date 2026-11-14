//! `gamelist.xml` of the EmulationStation, read and written without reformatting
//! (lume-launcher D4, spec game-library).
//!
//! The file is kept as text. Parsing only records where each `<game>` element and each of its
//! children start and end, so:
//! - an existing entry is never rewritten: unknown fields of a scraper stay byte for byte;
//! - a new game is inserted before `</gameList>`;
//! - a field change (`favorite`, `playcount`, `lastplayed`) replaces only the text of that
//!   child, or inserts the child before `</game>`.
//!
//! Entries are matched by `<path>`, normalized relative to the system folder.

use std::ops::Range;
use std::path::Path;

use quick_xml::events::Event;
use quick_xml::Reader;

pub const EMPTY: &str = "<?xml version=\"1.0\"?>\n<gameList>\n</gameList>\n";

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Child {
    pub name: String,
    /// The whole element, `<name>..</name>` or `<name/>`
    pub outer: Range<usize>,
    /// The text between the tags (empty range at the end of `<name/>`)
    pub inner: Range<usize>,
    pub text: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Entry {
    /// The whole `<game>` element
    pub span: Range<usize>,
    /// Position of `</game>`
    pub close: usize,
    pub children: Vec<Child>,
    /// `<path>` normalized (see [`normalize`])
    pub key: String,
}

impl Entry {
    pub fn field(&self, name: &str) -> Option<&str> {
        self.children.iter().find(|c| c.name == name).map(|c| c.text.as_str())
    }
}

#[derive(Debug, Clone)]
pub struct Gamelist {
    pub text: String,
    pub entries: Vec<Entry>,
    /// Position of `</gameList>`, or of `<gameList/>` when the root is empty
    root_close: usize,
    root_empty: Option<Range<usize>>,
}

/// Path of a game relative to its system folder, without `./`, with `/` separators. An
/// absolute path under `system_dir` is made relative; any other absolute path is kept.
pub fn normalize(path: &str, system_dir: &Path) -> String {
    let p = path.trim();
    let dir = system_dir.to_string_lossy();
    let rel = if let Some(rest) = p.strip_prefix(dir.as_ref()) {
        rest.trim_start_matches('/')
    } else {
        p
    };
    let mut parts: Vec<&str> = Vec::new();
    for part in rel.split('/') {
        match part {
            "" | "." => {}
            ".." => {
                parts.pop();
            }
            other => parts.push(other),
        }
    }
    let joined = parts.join("/");
    if rel.starts_with('/') {
        format!("/{joined}")
    } else {
        joined
    }
}

pub fn escape(text: &str) -> String {
    let mut out = String::with_capacity(text.len());
    for c in text.chars() {
        match c {
            '&' => out.push_str("&amp;"),
            '<' => out.push_str("&lt;"),
            '>' => out.push_str("&gt;"),
            '"' => out.push_str("&quot;"),
            '\'' => out.push_str("&apos;"),
            c => out.push(c),
        }
    }
    out
}

impl Gamelist {
    pub fn empty() -> Gamelist {
        Gamelist::parse(EMPTY.to_string(), Path::new("")).expect("empty gamelist parses")
    }

    pub fn parse(text: String, system_dir: &Path) -> Result<Gamelist, String> {
        let mut reader = Reader::from_str(&text);
        reader.config_mut().trim_text(false);
        let mut entries = Vec::new();
        let mut depth = 0usize;
        let mut root_seen = false;
        let mut root_close = None;
        let mut root_empty = None;
        // current game: start, children
        let mut game: Option<(usize, Vec<Child>)> = None;
        // current child at depth 2: name, outer start, inner start, text
        let mut child: Option<(String, usize, usize, String)> = None;
        loop {
            let before = reader.buffer_position() as usize;
            let ev = reader.read_event().map_err(|e| format!("at byte {before}: {e}"))?;
            let after = reader.buffer_position() as usize;
            match ev {
                Event::Start(e) => {
                    let name = String::from_utf8_lossy(e.local_name().as_ref()).into_owned();
                    depth += 1;
                    match depth {
                        1 if name == "gameList" => root_seen = true,
                        1 => return Err(format!("root element is {name}, not gameList")),
                        2 if name == "game" => game = Some((before, Vec::new())),
                        3 if game.is_some() => child = Some((name, before, after, String::new())),
                        _ => {}
                    }
                }
                Event::Empty(e) => {
                    let name = String::from_utf8_lossy(e.local_name().as_ref()).into_owned();
                    if depth == 0 && name == "gameList" {
                        root_seen = true;
                        root_empty = Some(before..after);
                    } else if depth == 2 {
                        if let Some((_, children)) = game.as_mut() {
                            children.push(Child { name, outer: before..after, inner: after..after, text: String::new() });
                        }
                    }
                }
                Event::Text(t) => {
                    if let Some((_, _, _, text)) = child.as_mut() {
                        text.push_str(&t.unescape().map_err(|e| e.to_string())?);
                    }
                }
                Event::CData(t) => {
                    if let Some((_, _, _, text)) = child.as_mut() {
                        text.push_str(&String::from_utf8_lossy(&t));
                    }
                }
                Event::End(_) => {
                    match depth {
                        3 => {
                            if let (Some((name, outer, inner, text)), Some((_, children))) = (child.take(), game.as_mut()) {
                                children.push(Child { name, outer: outer..after, inner: inner..before, text });
                            }
                        }
                        2 => {
                            if let Some((start, children)) = game.take() {
                                let key = children
                                    .iter()
                                    .find(|c| c.name == "path")
                                    .map(|c| normalize(&c.text, system_dir))
                                    .unwrap_or_default();
                                entries.push(Entry { span: start..after, close: before, children, key });
                            }
                        }
                        1 => root_close = Some(before),
                        _ => {}
                    }
                    depth = depth.saturating_sub(1);
                }
                Event::Eof => break,
                _ => {}
            }
        }
        if !root_seen {
            return Err("no gameList element".into());
        }
        let root_close = match (root_close, &root_empty) {
            (Some(p), _) => p,
            (None, Some(r)) => r.start,
            (None, None) => return Err("gameList is not closed".into()),
        };
        Ok(Gamelist { text, entries, root_close, root_empty })
    }

    pub fn load(path: &Path, system_dir: &Path) -> Result<Option<Gamelist>, String> {
        match std::fs::read(path) {
            Ok(bytes) => {
                let text = String::from_utf8(bytes).map_err(|_| "not UTF-8".to_string())?;
                Gamelist::parse(text, system_dir).map(Some)
            }
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(None),
            Err(e) => Err(e.to_string()),
        }
    }

    pub fn find(&self, key: &str) -> Option<&Entry> {
        self.entries.iter().find(|e| e.key == key)
    }

    /// Text with new `<game>` entries (relative path, name) inserted before `</gameList>`.
    pub fn with_new_games(&self, games: &[(String, String)]) -> String {
        if games.is_empty() {
            return self.text.clone();
        }
        let mut block = String::new();
        for (path, name) in games {
            block.push_str(&format!(
                "\t<game>\n\t\t<path>./{}</path>\n\t\t<name>{}</name>\n\t</game>\n",
                escape(path),
                escape(name)
            ));
        }
        let mut out = String::with_capacity(self.text.len() + block.len() + 16);
        match &self.root_empty {
            Some(r) => {
                out.push_str(&self.text[..r.start]);
                out.push_str("<gameList>\n");
                out.push_str(&block);
                out.push_str("</gameList>");
                out.push_str(&self.text[r.end..]);
            }
            None => {
                let at = self.root_close;
                out.push_str(&self.text[..at]);
                // keep the closing tag on its own line
                if !self.text[..at].ends_with('\n') {
                    out.push('\n');
                }
                out.push_str(&block);
                out.push_str(&self.text[at..]);
            }
        }
        out
    }

    /// Text with the fields of one entry set (replaced in place, or inserted before
    /// `</game>`); `None` if the entry does not exist.
    pub fn with_fields(&self, key: &str, fields: &[(&str, String)]) -> Option<String> {
        let entry = self.find(key)?;
        // edits from the end, so earlier positions stay valid
        let mut edits: Vec<(Range<usize>, String)> = Vec::new();
        let mut inserts = String::new();
        for (name, value) in fields {
            match entry.children.iter().find(|c| c.name == *name) {
                Some(c) if c.inner.is_empty() && c.outer.end == c.inner.end => {
                    // <name/>
                    edits.push((c.outer.clone(), format!("<{name}>{}</{name}>", escape(value))));
                }
                Some(c) => edits.push((c.inner.clone(), escape(value))),
                None => inserts.push_str(&format!("\t\t<{name}>{}</{name}>\n", escape(value))),
            }
        }
        if !inserts.is_empty() {
            // before the indentation of </game> when it sits on its own line
            let line_start = self.text[..entry.close].rfind('\n').map(|p| p + 1).unwrap_or(entry.close);
            let at = if self.text[line_start..entry.close].trim().is_empty() { line_start } else { entry.close };
            let ins = if at == entry.close { format!("\n{inserts}\t") } else { inserts };
            edits.push((at..at, ins));
        }
        edits.sort_by_key(|(r, _)| std::cmp::Reverse(r.start));
        let mut out = self.text.clone();
        for (range, value) in edits {
            out.replace_range(range, &value);
        }
        Some(out)
    }
}

/// `lastplayed` of the EmulationStation (`20261114T183000`, local time taken as UTC) to unix
/// seconds; 0 when absent or malformed.
pub fn parse_es_time(s: &str) -> u32 {
    let s = s.trim();
    let digits: String = s.chars().filter(|c| c.is_ascii_digit()).collect();
    if digits.len() < 14 {
        return 0;
    }
    let n = |r: Range<usize>| digits[r].parse::<i64>().unwrap_or(0);
    let (y, mo, d, h, mi, se) = (n(0..4), n(4..6), n(6..8), n(8..10), n(10..12), n(12..14));
    if !(1970..=2105).contains(&y) || !(1..=12).contains(&mo) || !(1..=31).contains(&d) {
        return 0;
    }
    let days = days_from_civil(y, mo, d);
    (days * 86400 + h * 3600 + mi * 60 + se).clamp(0, u32::MAX as i64) as u32
}

pub fn format_es_time(secs: u64) -> String {
    let days = (secs / 86400) as i64;
    let rem = secs % 86400;
    let (y, m, d) = civil_from_days(days);
    format!("{y:04}{m:02}{d:02}T{:02}{:02}{:02}", rem / 3600, rem % 3600 / 60, rem % 60)
}

// Howard Hinnant's civil date algorithms
fn days_from_civil(y: i64, m: i64, d: i64) -> i64 {
    let y = if m <= 2 { y - 1 } else { y };
    let era = y.div_euclid(400);
    let yoe = y - era * 400;
    let doy = (153 * (if m > 2 { m - 3 } else { m + 9 }) + 2) / 5 + d - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    era * 146097 + doe - 719468
}

fn civil_from_days(z: i64) -> (i64, i64, i64) {
    let z = z + 719468;
    let era = z.div_euclid(146097);
    let doe = z - era * 146097;
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    (if m <= 2 { y + 1 } else { y }, m, d)
}

#[cfg(test)]
mod tests {
    use super::*;

    const SCRAPED: &str = r#"<?xml version="1.0"?>
<gameList>
	<game id="1234" source="ScreenScraper.fr">
		<path>./Alpha (USA).sfc</path>
		<name>Alpha &amp; Beta</name>
		<desc>A game.</desc>
		<image>./images/Alpha (USA)-image.png</image>
		<rating>0.8</rating>
		<favorite/>
		<unknowntag weird="yes">keep me</unknowntag>
	</game>
	<folder><path>./sub</path><name>Sub</name></folder>
</gameList>
"#;

    #[test]
    fn parses_entries_and_fields() {
        let g = Gamelist::parse(SCRAPED.into(), Path::new("/storage/roms/snes")).unwrap();
        assert_eq!(g.entries.len(), 1);
        let e = &g.entries[0];
        assert_eq!(e.key, "Alpha (USA).sfc");
        assert_eq!(e.field("name"), Some("Alpha & Beta"));
        assert_eq!(e.field("image"), Some("./images/Alpha (USA)-image.png"));
        assert_eq!(&SCRAPED[e.span.clone()][..6], "<game ");
        assert!(SCRAPED[e.span.clone()].ends_with("</game>"));
    }

    #[test]
    fn new_games_keep_existing_bytes() {
        let g = Gamelist::parse(SCRAPED.into(), Path::new("/r")).unwrap();
        let out = g.with_new_games(&[("New & Co.sfc".into(), "New & Co".into())]);
        let old_entry = &SCRAPED[g.entries[0].span.clone()];
        assert!(out.contains(old_entry));
        assert!(out.starts_with(&SCRAPED[..g.entries[0].span.end]));
        assert!(out.contains("<path>./New &amp; Co.sfc</path>"));
        let again = Gamelist::parse(out, Path::new("/r")).unwrap();
        assert_eq!(again.entries.len(), 2);
        assert_eq!(again.entries[1].field("name"), Some("New & Co"));
        assert_eq!(again.entries[0].field("unknowntag"), Some("keep me"));
    }

    #[test]
    fn fields_replace_or_insert() {
        let g = Gamelist::parse(SCRAPED.into(), Path::new("/r")).unwrap();
        let out = g
            .with_fields("Alpha (USA).sfc", &[("favorite", "true".into()), ("playcount", "3".into()), ("rating", "0.9".into())])
            .unwrap();
        let g2 = Gamelist::parse(out.clone(), Path::new("/r")).unwrap();
        let e = &g2.entries[0];
        assert_eq!(e.field("favorite"), Some("true"));
        assert_eq!(e.field("playcount"), Some("3"));
        assert_eq!(e.field("rating"), Some("0.9"));
        assert_eq!(e.field("desc"), Some("A game."));
        assert!(out.contains("<unknowntag weird=\"yes\">keep me</unknowntag>"));
        assert!(out.contains("\t\t<playcount>3</playcount>\n\t</game>"));
        assert!(g.with_fields("missing", &[("favorite", "true".into())]).is_none());
    }

    #[test]
    fn empty_root_and_errors() {
        let g = Gamelist::parse("<?xml version=\"1.0\"?>\n<gameList/>\n".into(), Path::new("/r")).unwrap();
        let out = g.with_new_games(&[("a.nes".into(), "a".into())]);
        assert_eq!(Gamelist::parse(out, Path::new("/r")).unwrap().entries.len(), 1);
        assert!(Gamelist::parse("<other/>".into(), Path::new("/r")).is_err());
        assert!(Gamelist::parse("<gameList><game>".into(), Path::new("/r")).is_err());
        assert_eq!(Gamelist::empty().entries.len(), 0);
    }

    #[test]
    fn path_normalization() {
        let d = Path::new("/storage/roms/snes");
        assert_eq!(normalize("./a.sfc", d), "a.sfc");
        assert_eq!(normalize("/storage/roms/snes/sub/a.sfc", d), "sub/a.sfc");
        assert_eq!(normalize("./sub/../a.sfc", d), "a.sfc");
        assert_eq!(normalize("/other/a.sfc", d), "/other/a.sfc");
    }

    #[test]
    fn es_time_round_trip() {
        let t = parse_es_time("20261114T183005");
        assert_eq!(format_es_time(t as u64), "20261114T183005");
        assert_eq!(parse_es_time(""), 0);
        assert_eq!(parse_es_time("garbage"), 0);
    }
}
