//! Text folding for sorting and searching (spec game-launcher, "Busca por nome"): case and
//! the accents of the Latin letters used by en, pt and es (and the other Western European
//! languages) are ignored. No Unicode tables: a small fixed map is enough for game names.

fn base(c: char) -> Option<&'static str> {
    Some(match c {
        'à' | 'á' | 'â' | 'ã' | 'ä' | 'å' | 'ā' => "a",
        'æ' => "ae",
        'ç' | 'ć' | 'č' => "c",
        'è' | 'é' | 'ê' | 'ë' | 'ē' | 'ę' | 'ě' => "e",
        'ì' | 'í' | 'î' | 'ï' | 'ī' => "i",
        'ñ' | 'ń' | 'ň' => "n",
        'ò' | 'ó' | 'ô' | 'õ' | 'ö' | 'ø' | 'ō' | 'ő' => "o",
        'œ' => "oe",
        'ù' | 'ú' | 'û' | 'ü' | 'ū' | 'ů' | 'ű' => "u",
        'ý' | 'ÿ' => "y",
        'ß' => "ss",
        'ł' => "l",
        'š' | 'ś' => "s",
        'ž' | 'ź' | 'ż' => "z",
        'ř' => "r",
        'ð' => "d",
        'þ' => "th",
        _ => return None,
    })
}

/// Lowercase without accents.
pub fn fold(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    for c in s.chars().flat_map(char::to_lowercase) {
        match base(c) {
            Some(b) => out.push_str(b),
            None => out.push(c),
        }
    }
    out
}

/// Whether `name` contains every word of `query` (folded); an empty query matches all.
pub fn matches(name: &str, query: &str) -> bool {
    let name = fold(name);
    fold(query).split_whitespace().all(|w| name.contains(w))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn fold_and_match() {
        assert_eq!(fold("Ação ÉPICA Ñ"), "acao epica n");
        assert!(matches("Super Mario Bros. 3", "super bros"));
        assert!(matches("Pokémon Edição", "POKEMON edicao"));
        assert!(!matches("Super Metroid", "super bros"));
        assert!(matches("anything", "  "));
    }
}
