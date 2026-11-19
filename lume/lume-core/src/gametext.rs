//! The texts of the Lume menu over a game and of the chord hint (lume-hud-actions D10, D13),
//! in the launcher's languages (en, pt, es). The language is the launcher's
//! (`settings.toml`, read as lume-ui reads it).

use std::path::Path;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Text {
    BackToGame,
    Reset,
    /// "<App> menu": the application's own menu (RetroArch's)
    AppMenu,
    EndGame,
    ForceClose,
    ConfirmReset,
    ConfirmEnd,
    No,
    Yes,
    NotResponding,
    SaveState,
    LoadState,
    Screenshot,
    StatusBar,
    /// the footer hints of the menu: A, B
    HintSelect,
    HintBack,
}

/// The display name of a runner for "<App> menu" and "<App> is not responding".
pub fn app_name(runner_id: &str) -> String {
    match runner_id {
        "retroarch" => "RetroArch".into(),
        "love" => "LÖVE".into(),
        id => {
            let mut c = id.chars();
            c.next().map(|f| f.to_uppercase().collect::<String>() + c.as_str()).unwrap_or_default()
        }
    }
}

/// One text in `lang` (en for an unknown language); `app` fills the runner's name.
pub fn text(lang: &str, t: Text, app: &str) -> String {
    use Text::*;
    let s = match lang {
        "pt" => match t {
            BackToGame => "Voltar ao jogo",
            Reset => "Reiniciar",
            AppMenu => return format!("Menu do {app}"),
            EndGame => "Encerrar jogo",
            ForceClose => "Forçar fechamento",
            ConfirmReset => "Reiniciar o jogo?",
            ConfirmEnd => "Encerrar o jogo?",
            No => "Não",
            Yes => "Sim",
            NotResponding => return format!("{app} não responde"),
            SaveState => "Salvar estado",
            LoadState => "Carregar estado",
            Screenshot => "Capturar a tela",
            StatusBar => "Barra de status",
            HintSelect => "Escolher",
            HintBack => "Voltar",
        },
        "es" => match t {
            BackToGame => "Volver al juego",
            Reset => "Reiniciar",
            AppMenu => return format!("Menú de {app}"),
            EndGame => "Salir del juego",
            ForceClose => "Forzar cierre",
            ConfirmReset => "¿Reiniciar el juego?",
            ConfirmEnd => "¿Salir del juego?",
            No => "No",
            Yes => "Sí",
            NotResponding => return format!("{app} no responde"),
            SaveState => "Guardar estado",
            LoadState => "Cargar estado",
            Screenshot => "Capturar la pantalla",
            StatusBar => "Barra de estado",
            HintSelect => "Elegir",
            HintBack => "Volver",
        },
        _ => match t {
            BackToGame => "Back to game",
            Reset => "Reset",
            AppMenu => return format!("{app} menu"),
            EndGame => "End game",
            ForceClose => "Force close",
            ConfirmReset => "Reset the game?",
            ConfirmEnd => "End the game?",
            No => "No",
            Yes => "Yes",
            NotResponding => return format!("{app} is not responding"),
            SaveState => "Save state",
            LoadState => "Load state",
            Screenshot => "Screenshot",
            StatusBar => "Status bar",
            HintSelect => "Select",
            HintBack => "Back",
        },
    };
    s.into()
}

/// The launcher's language from `ROMS/system/lume/settings.toml` (en when unset).
pub fn language(card: &Path) -> String {
    crate::settings::Settings::load(&card.join("settings.toml")).language
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn every_text_in_the_three_languages() {
        use Text::*;
        let all = [BackToGame, Reset, AppMenu, EndGame, ForceClose, ConfirmReset, ConfirmEnd, No, Yes,
                   NotResponding, SaveState, LoadState, Screenshot, StatusBar, HintSelect, HintBack];
        for lang in crate::settings::LANGUAGES {
            for t in all {
                let s = text(lang, t, "RetroArch");
                assert!(!s.is_empty() && !s.contains(['|', '\n', '\t']), "{lang} {t:?}");
            }
        }
        assert_eq!(text("pt", AppMenu, "RetroArch"), "Menu do RetroArch");
        assert_eq!(text("es", ConfirmEnd, ""), "¿Salir del juego?");
        assert_eq!(text("xx", BackToGame, ""), "Back to game");
        assert_eq!(app_name("retroarch"), "RetroArch");
        assert_eq!(app_name("sh"), "Sh");
    }
}
