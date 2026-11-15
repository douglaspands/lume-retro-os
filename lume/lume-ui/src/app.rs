//! The launcher itself (lume-launcher tasks 7.3 to 7.7): screens, overlays and navigation,
//! drawn through [`Canvas`]. Event driven: `handle` changes the state and says whether a
//! frame is needed, `draw` paints one frame, `wait` says how long the main loop may sleep
//! (forever unless an animation, the System panel or a toast needs a wake-up).

use std::collections::BTreeMap;
use std::path::PathBuf;
use std::time::{Duration, Instant};

use lume_core::catalog::{Catalog, Emulator};
use lume_core::options::{Field, Layer, Options};
use lume_core::runner::{Kind, Runner};
use lume_core::settings::Settings;

use crate::canvas::{Align, Canvas, Rect, TextureId};
use crate::i18n::{Texts, LANGUAGES};
use crate::input::Action;
use crate::launch::{self, Dirs, Slot, ASPECTS};
use crate::library::{GameRef, Library};
use crate::lru::Lru;
use crate::state::State;
use crate::system::SystemAdapter;
use crate::theme::{Theme, Themes};

/// lume-run codes (D1)
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Exit {
    Shutdown = 0,
    Launch = 64,
    RetroArch = 65,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Ev {
    Input(Action, bool),
    /// a timer of `wait` expired
    Tick,
    /// the index generation changed (scan finished)
    Reload,
    /// a line of `lume-index --progress`
    Progress(usize, usize),
    UpdateDone(bool),
    /// a volume key changed the level (percent), told by the input daemon
    Volume(u8),
    /// the battery level (percent) or charging state changed
    Battery(u8, bool),
    /// Wi-Fi or Bluetooth connected or not any more (Wi-Fi, Bluetooth)
    Network(bool, bool),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DockItem {
    Favorites,
    System(usize),
    Recent,
    Settings,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ListKind {
    System(usize),
    Favorites,
    Recent,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Screen {
    Dock,
    Grid,
    Settings,
}

pub struct Grid {
    pub kind: ListKind,
    pub all: Vec<GameRef>,
    pub items: Vec<GameRef>,
    pub focus: usize,
    pub top: usize,
    pub filter: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Row {
    Start,
    StartState,
    /// opens the game's Settings submenu
    Settings,
    Emulator,
    Aspect,
    Shader,
    Favorite,
    ClearGames,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SetRow {
    Wifi,
    Bluetooth,
    Language,
    Theme,
    /// display options: the battery's percent
    Display,
    Volume,
    Brightness,
    System,
    Update,
    RetroArch,
    Power,
}

enum Overlay {
    /// game menu (Some(game)) or console options (None) of a system; `sub`: the game's
    /// Settings submenu (emulator, aspect, shader)
    Menu { sys: usize, game: Option<GameRef>, focus: usize, sub: bool },
    /// save states of a game with the picture of the focused one
    Slots { game: GameRef, slots: Vec<String>, focus: usize },
    Keyboard { focus: usize },
    Confirm { focus: usize },
}

/// L1/R1: a share of the list, never less than a page, faster when repeated quickly.
pub struct Jump {
    last: Option<(Instant, i32)>,
    pub speed: usize,
}

impl Jump {
    pub fn step(&mut self, now: Instant, dir: i32, len: usize, page: usize) -> usize {
        self.speed = match self.last {
            Some((t, d)) if d == dir && now.duration_since(t) < Duration::from_millis(700) => (self.speed * 2).min(8),
            _ => 1,
        };
        self.last = Some((now, dir));
        (len / 20).max(page).max(1) * self.speed
    }
}

/// Search keyboard (prototype): numbers, then QWERTY; the filter ignores case.
const KEYS: &[&str] = &["1234567890", "QWERTYUIOP", "ASDFGHJKL", "ZXCVBNM"];
/// keys of the last keyboard row, after the characters: space, backspace, clear, OK
const KEY_ACTIONS: usize = 4;
/// the keyboard opens on Q (row 1, column 0); focus is row * 16 + column
const KEY_START: usize = 16;
/// longest search text (prototype)
const SEARCH_MAX: usize = 24;
/// games in Recent
const RECENT_MAX: usize = 50;
/// The "button" of a hint for the left/right arrows: drawn as two triangles in a tonal chip
/// (the font has no ◀▶).
pub const NAV_LR: &str = "◀▶";
/// The same for up/down (▲▼).
pub const NAV_UD: &str = "▲▼";

pub struct App<S: SystemAdapter> {
    pub texts: Texts,
    pub theme: Theme,
    themes: Themes,
    pub settings: Settings,
    settings_path: PathBuf,
    share: PathBuf,
    card: PathBuf,
    pub runtime: PathBuf,
    ra_cfg: PathBuf,
    catalog: Catalog,
    runners: BTreeMap<String, Runner>,
    options: Options,
    pub lib: Library,
    dirs: Dirs,
    arch: String,
    pub sys: S,
    pub screen: Screen,
    overlay: Option<Overlay>,
    toast: Option<(String, Instant)>,
    /// the volume bar outside the Settings: level and when it goes away
    pub volume_bar: Option<(u8, Instant)>,
    /// the status bar's battery: level and charging (None: no battery, nothing drawn)
    pub battery: Option<(u8, bool)>,
    /// the status bar's network: (Wi-Fi connected, Bluetooth connected)
    pub network: (bool, bool),
    pub dock: Vec<DockItem>,
    pub dock_focus: usize,
    pub grid: Option<Grid>,
    pub settings_focus: usize,
    info: Option<(Instant, Vec<(&'static str, String)>)>,
    level: BTreeMap<&'static str, u8>,
    /// cover texture and the part of it that is the image
    thumbs: Lru<GameRef, (TextureId, Rect)>,
    free_list: Vec<TextureId>,
    /// Dock icons of a card theme (icons/<system>.png), per system id; None: no icon
    icons: BTreeMap<String, Option<(TextureId, Rect)>>,
    /// the picture of the save state slot on screen: its file and texture (one at a time)
    slot_pic: Option<(PathBuf, Option<(TextureId, Rect)>)>,
    pub jump: Jump,
    pub exit: Option<Exit>,
    pub updating: Option<(usize, usize)>,
    /// asks the main loop to start `lume-index --progress`
    pub start_update: bool,
    anim: Option<(Instant, f32)>,
    pub cols: usize,
    pub rows: usize,
}

pub struct Paths {
    pub storage: PathBuf,
    pub share: PathBuf,
    pub cores: PathBuf,
    pub runtime: PathBuf,
    pub ra_cfg: PathBuf,
}

const TOAST: Duration = Duration::from_millis(1800);
/// the volume bar stays this long after the last volume key
pub const VOLUME_BAR: Duration = Duration::from_millis(1500);
/// Frame interval while an animation runs: 60 fps, the screen's rate (30 fps made the Dock
/// look jerky; the animation is still 0.2 s, only drawn with more steps)
const FRAME: Duration = Duration::from_millis(16);

impl<S: SystemAdapter> App<S> {
    pub fn new(p: Paths, catalog: Catalog, runners: BTreeMap<String, Runner>, arch: &str, sys: S) -> App<S> {
        let card = p.storage.join("system/lume");
        let settings_path = card.join("settings.toml");
        let settings = Settings::load(&settings_path);
        let themes = Themes::new(&card, &p.share);
        let theme = themes.load_or_default(&settings.theme);
        let cache = theme.num("cache_bytes") as usize;
        let lib = Library::load(&card, &catalog);
        let mut app = App {
            texts: Texts::load(&p.share.join("i18n"), &settings.language),
            theme,
            themes,
            settings,
            settings_path,
            share: p.share.clone(),
            options: Options::new(&card),
            card,
            runtime: p.runtime.clone(),
            ra_cfg: p.ra_cfg,
            catalog,
            runners,
            lib,
            dirs: Dirs { storage: p.storage, cores: p.cores },
            arch: arch.into(),
            sys,
            screen: Screen::Dock,
            overlay: None,
            toast: None,
            volume_bar: None,
            battery: None,
            network: (false, false),
            dock: Vec::new(),
            dock_focus: 0,
            grid: None,
            settings_focus: 0,
            info: None,
            level: BTreeMap::new(),
            thumbs: Lru::new(cache),
            free_list: Vec::new(),
            icons: BTreeMap::new(),
            slot_pic: None,
            jump: Jump { last: None, speed: 1 },
            exit: None,
            updating: None,
            start_update: false,
            anim: None,
            cols: 4,
            rows: 2,
        };
        app.battery = app.sys.battery();
        app.network = app.sys.network();
        app.build_dock();
        if let Some(st) = State::load(&app.runtime) {
            app.restore(&st);
        }
        app
    }

    pub fn tr(&self, key: &'static str) -> String {
        self.texts.get(key).to_string()
    }

    fn build_dock(&mut self) {
        self.dock = std::iter::once(DockItem::Favorites)
            .chain((0..self.lib.systems.len()).map(DockItem::System))
            .chain([DockItem::Recent, DockItem::Settings])
            .collect();
        self.dock_focus = self.dock_focus.min(self.dock.len() - 1);
    }

    fn dock_id(&self, item: DockItem) -> String {
        match item {
            DockItem::Favorites => "favorites".into(),
            DockItem::Recent => "recent".into(),
            DockItem::Settings => "settings".into(),
            DockItem::System(s) => format!("sys:{}", self.lib.systems[s].id),
        }
    }

    fn list_id(&self, k: ListKind) -> String {
        match k {
            ListKind::Favorites => "favorites".into(),
            ListKind::Recent => "recent".into(),
            ListKind::System(s) => format!("sys:{}", self.lib.systems[s].id),
        }
    }

    fn kind_from_id(&self, id: &str) -> Option<ListKind> {
        match id {
            "favorites" => Some(ListKind::Favorites),
            "recent" => Some(ListKind::Recent),
            s => s.strip_prefix("sys:").and_then(|i| self.lib.system_index(i)).map(ListKind::System),
        }
    }

    pub fn current_state(&self) -> State {
        let mut st = State {
            screen: match self.screen {
                Screen::Dock => "dock",
                Screen::Grid => "grid",
                Screen::Settings => "settings",
            }
            .into(),
            dock: self.dock_id(self.dock[self.dock_focus]),
            settings: self.settings_focus,
            ..Default::default()
        };
        if let Some(g) = &self.grid {
            st.list = self.list_id(g.kind);
            st.filter = g.filter.clone();
            if let Some(r) = g.items.get(g.focus) {
                st.game_system = self.lib.systems[r.sys].id.clone();
                st.game_path = self.lib.path(*r).into();
            }
        }
        st
    }

    /// Back to where the user was (after a game, or a reload of the index).
    pub fn restore(&mut self, st: &State) {
        if let Some(i) = self.dock.iter().position(|d| self.dock_id(*d) == st.dock) {
            self.dock_focus = i;
        }
        self.settings_focus = st.settings;
        match st.screen.as_str() {
            "grid" => {
                if let Some(k) = self.kind_from_id(&st.list) {
                    self.open_grid(k);
                    let g = self.grid.as_mut().unwrap();
                    g.filter = st.filter.clone();
                    self.apply_filter();
                    if let Some(r) = self.lib.find(&st.game_system, &st.game_path) {
                        let g = self.grid.as_mut().unwrap();
                        if let Some(i) = g.items.iter().position(|x| *x == r) {
                            g.focus = i;
                        }
                    }
                    self.screen = Screen::Grid;
                    self.scroll_to_focus();
                }
            }
            "settings" => {
                // back from RetroArch opened by the Settings: the levels are read again, as
                // when the screen is opened from the Dock
                self.screen = Screen::Settings;
                self.read_levels();
            }
            _ => self.screen = Screen::Dock,
        }
    }

    fn reload_library(&mut self) {
        let st = self.current_state();
        self.lib = Library::load(&self.card, &self.catalog);
        for (t, _) in self.thumbs.drain() {
            self.free_list.push(t);
        }
        self.build_dock();
        self.grid = None;
        self.restore(&st);
    }

    // ---- lists ----

    fn open_grid(&mut self, kind: ListKind) {
        let all = match kind {
            ListKind::System(s) => self.lib.games_of(s),
            ListKind::Favorites => self.lib.favorites(),
            ListKind::Recent => self.lib.recents(RECENT_MAX),
        };
        self.grid = Some(Grid { kind, items: all.clone(), all, focus: 0, top: 0, filter: String::new() });
    }

    /// Sets the search filter of the grid (what the on-screen keyboard types).
    pub fn search(&mut self, text: &str) {
        if let Some(g) = self.grid.as_mut() {
            g.filter = text.to_string();
        }
        self.apply_filter();
    }

    pub fn focused_name(&self) -> Option<String> {
        let g = self.grid.as_ref()?;
        g.items.get(g.focus).map(|r| self.lib.name(*r).to_string())
    }

    pub fn overlay_open(&self) -> bool {
        self.overlay.is_some()
    }

    /// Leaves the search: the text without edge spaces filters the list, from its first game.
    fn close_search(&mut self) {
        let Some(g) = self.grid.as_mut() else { return };
        g.filter = g.filter.trim().to_string();
        self.apply_filter();
        if let Some(g) = self.grid.as_mut() {
            g.focus = 0;
            g.top = 0;
        }
    }

    fn apply_filter(&mut self) {
        let Some(g) = self.grid.as_mut() else { return };
        let keep = g.items.get(g.focus).copied();
        g.items = g.all.iter().copied().filter(|r| lume_core::text::matches(self.lib.name(*r), &g.filter)).collect();
        g.focus = keep.and_then(|k| g.items.iter().position(|x| *x == k)).unwrap_or(0);
    }

    fn scroll_to_focus(&mut self) {
        let (cols, rows) = (self.cols, self.rows);
        if let Some(g) = self.grid.as_mut() {
            let row = g.focus / cols;
            if row < g.top {
                g.top = row;
            } else if row >= g.top + rows {
                g.top = row + 1 - rows;
            }
        }
    }

    fn page(&self) -> usize {
        self.cols * self.rows
    }

    // ---- events ----

    /// Handles one event; true when the screen must be drawn again.
    pub fn handle(&mut self, ev: Ev) -> bool {
        let now = Instant::now();
        match ev {
            Ev::Tick => {
                let mut redraw = false;
                if self.toast.as_ref().is_some_and(|(_, t)| now >= *t) {
                    self.toast = None;
                    redraw = true;
                }
                if self.volume_bar.is_some_and(|(_, t)| now >= t) {
                    self.volume_bar = None;
                    redraw = true;
                }
                if self.on_system_row() && self.info.as_ref().is_none_or(|(t, _)| now.duration_since(*t) >= Duration::from_millis(950)) {
                    self.info = Some((now, self.sys.info()));
                    redraw = true;
                }
                if let Some((t, _)) = self.anim {
                    if now.duration_since(t).as_millis() as f64 >= self.theme.num("anim_ms") {
                        self.anim = None;
                    }
                    redraw = true;
                }
                redraw
            }
            Ev::Reload => {
                if self.lib.changed() {
                    self.reload_library();
                    return true;
                }
                false
            }
            Ev::Progress(i, n) => {
                self.updating = Some((i, n));
                true
            }
            Ev::UpdateDone(ok) => {
                self.updating = None;
                self.reload_library();
                if ok {
                    self.toast_key("updated");
                }
                true
            }
            Ev::Volume(v) => {
                // the Settings show it in the Volume row; elsewhere, the bar
                self.level.insert("volume", v);
                self.volume_bar = (self.screen != Screen::Settings).then_some((v, now + VOLUME_BAR));
                true
            }
            Ev::Battery(level, charging) => {
                let new = Some((level.min(100), charging));
                let changed = self.battery != new;
                self.battery = new;
                changed
            }
            Ev::Network(wifi, bt) => {
                let changed = self.network != (wifi, bt);
                self.network = (wifi, bt);
                changed
            }
            Ev::Input(a, repeat) => {
                if self.updating.is_some() {
                    return false; // the lists are being rebuilt
                }
                let before = self.on_system_row();
                self.input(a, repeat, now);
                if !self.on_system_row() {
                    self.info = None; // leaving the item stops the reading
                } else if !before {
                    self.info = Some((now, self.sys.info()));
                }
                true
            }
        }
    }

    fn on_system_row(&self) -> bool {
        self.screen == Screen::Settings && self.overlay.is_none() && self.set_rows().get(self.settings_focus) == Some(&SetRow::System)
    }

    /// How long the main loop may wait for an event (None: until one comes).
    pub fn wait(&self) -> Option<Duration> {
        let now = Instant::now();
        let mut w: Option<Duration> = None;
        let mut min = |d: Duration| w = Some(w.map_or(d, |x: Duration| x.min(d)));
        if self.anim.is_some() {
            min(FRAME);
        }
        if let Some((_, t)) = &self.toast {
            min(t.saturating_duration_since(now));
        }
        if let Some((_, t)) = &self.volume_bar {
            min(t.saturating_duration_since(now));
        }
        if self.on_system_row() {
            min(Duration::from_millis(1000));
        }
        w
    }

    fn toast_key(&mut self, key: &'static str) {
        self.toast = Some((self.tr(key), Instant::now() + TOAST));
    }

    fn animate(&mut self, from: f32) {
        if self.theme.num("anim_ms") > 0.0 {
            self.anim = Some((Instant::now(), from));
        }
    }

    fn input(&mut self, a: Action, repeat: bool, now: Instant) {
        if let Some(ov) = self.overlay.take() {
            self.overlay = self.overlay_input(ov, a, repeat);
            return;
        }
        match self.screen {
            Screen::Dock => self.dock_input(a),
            Screen::Grid => self.grid_input(a, now),
            Screen::Settings => self.settings_input(a, repeat),
        }
    }

    fn dock_input(&mut self, a: Action) {
        let n = self.dock.len();
        match a {
            Action::Left => {
                self.dock_focus = (self.dock_focus + n - 1) % n;
                self.animate(-1.0);
            }
            Action::Right => {
                self.dock_focus = (self.dock_focus + 1) % n;
                self.animate(1.0);
            }
            Action::A | Action::Start => match self.dock[self.dock_focus] {
                DockItem::Settings => {
                    self.screen = Screen::Settings;
                    self.settings_focus = 0;
                    self.read_levels();
                }
                DockItem::Favorites => self.enter(ListKind::Favorites),
                DockItem::Recent => self.enter(ListKind::Recent),
                DockItem::System(s) => self.enter(ListKind::System(s)),
            },
            _ => {}
        }
    }

    fn enter(&mut self, k: ListKind) {
        self.open_grid(k);
        self.screen = Screen::Grid;
    }

    fn grid_input(&mut self, a: Action, now: Instant) {
        let cols = self.cols;
        let page = self.page();
        let Some(g) = self.grid.as_mut() else { return };
        let n = g.items.len();
        match a {
            Action::B => {
                if !g.filter.is_empty() {
                    g.filter.clear();
                    self.apply_filter();
                } else {
                    self.grid = None;
                    self.screen = Screen::Dock;
                }
                return;
            }
            Action::X => {
                self.overlay = Some(Overlay::Keyboard { focus: KEY_START });
                return;
            }
            Action::Y => {
                if let ListKind::System(s) = g.kind {
                    self.overlay = Some(Overlay::Menu { sys: s, game: None, focus: 0, sub: false });
                }
                return;
            }
            _ => {}
        }
        if n == 0 {
            return;
        }
        let f = g.focus;
        g.focus = match a {
            Action::Left => f.saturating_sub(1),
            Action::Right => (f + 1).min(n - 1),
            Action::Up => f.saturating_sub(cols),
            Action::Down => {
                if f + cols < n {
                    f + cols
                } else if f / cols < (n - 1) / cols {
                    n - 1
                } else {
                    f
                }
            }
            Action::L1 => f.saturating_sub(self.jump.step(now, -1, n, page)),
            Action::R1 => (f + self.jump.step(now, 1, n, page)).min(n - 1),
            Action::A | Action::Start => {
                let game = g.items[f];
                self.overlay = Some(Overlay::Menu { sys: game.sys, game: Some(game), focus: 0, sub: false });
                f
            }
            _ => f,
        };
        self.scroll_to_focus();
    }

    // ---- game menu and console options ----

    fn runner_of(&self, e: &Emulator) -> Option<&Runner> {
        self.runners.get(&e.runner)
    }

    fn system_of(&self, sys: usize) -> &lume_core::catalog::System {
        self.catalog.system(&self.lib.systems[sys].id).expect("library systems come from the catalog")
    }

    fn effective(&self, sys: usize, game: Option<GameRef>) -> lume_core::options::Effective {
        let s = self.system_of(sys);
        match game {
            Some(g) => self.options.resolve(s, &self.arch, self.lib.path(g)),
            None => Options::resolve_layers(s, &self.arch, &self.options.system(&s.id), &Layer::default()),
        }
    }

    /// Rows of a menu: the game menu (start, save states, settings, favorite), the game's
    /// Settings submenu, or the console options. Aspect and shader only for a libretro core.
    fn menu_rows(&self, sys: usize, game: Option<GameRef>, sub: bool) -> Vec<Row> {
        if game.is_some() && !sub {
            return vec![Row::Start, Row::StartState, Row::Settings, Row::Favorite];
        }
        let eff = self.effective(sys, game);
        let libretro = self.runner_of(&eff.emulator).is_some_and(|r| r.kind == Kind::Libretro);
        let mut rows = vec![Row::Emulator];
        if libretro {
            rows.extend([Row::Aspect, Row::Shader]);
        }
        if game.is_none() {
            rows.push(Row::ClearGames);
        }
        rows
    }

    /// Save state slots of a game split by the effective core (D7, the lume registry).
    fn slots(&self, g: GameRef) -> lume_core::states::Slots {
        let eff = self.effective(g.sys, Some(g));
        let rom = self.dirs.rom(&self.lib.systems[g.sys].id, self.lib.path(g));
        let prefix = self.dirs.states_prefix(&rom);
        let base = prefix.file_name().map(|b| b.to_string_lossy().into_owned()).unwrap_or_default();
        let existing: Vec<String> = std::fs::read_dir(prefix.parent().unwrap_or(&prefix))
            .map(|d| {
                d.flatten()
                    .filter_map(|e| {
                        let name = e.file_name().to_string_lossy().into_owned();
                        let rest = name.strip_prefix(&base)?.strip_prefix(".state")?;
                        match rest {
                            "" => Some("0".to_string()),
                            ".auto" => Some("auto".to_string()),
                            n if n.chars().all(|c| c.is_ascii_digit()) => Some(n.trim_start_matches('0').to_string()).map(|s| if s.is_empty() { "0".into() } else { s }),
                            _ => None,
                        }
                    })
                    .collect()
            })
            .unwrap_or_default();
        let recorded = lume_core::states::cores(&self.card, &self.lib.systems[g.sys].id, self.lib.path(g));
        lume_core::states::usable(&existing, &recorded, eff.emulator.core.as_deref().unwrap_or(""))
    }

    fn shaders(&self) -> Vec<String> {
        let dir = PathBuf::from("/usr/share/libretro/shaders/lume-shaders");
        let mut out = Vec::new();
        fn walk(d: &std::path::Path, out: &mut Vec<String>) {
            let Ok(e) = std::fs::read_dir(d) else { return };
            for e in e.flatten() {
                let p = e.path();
                if p.is_dir() {
                    walk(&p, out);
                } else if p.extension().is_some_and(|x| x == "glslp") {
                    out.push(p.to_string_lossy().into_owned());
                }
            }
        }
        walk(&dir, &mut out);
        out.sort();
        out
    }

    /// The values of a cycling row: None is "Default" (no exception at this layer).
    fn row_values(&self, sys: usize, row: Row) -> Vec<Option<String>> {
        let mut v: Vec<Option<String>> = vec![None];
        match row {
            Row::Emulator => {
                for e in self.system_of(sys).emulators(&self.arch) {
                    v.push(Some(format!("{}|{}", e.runner, e.core.unwrap_or_default())));
                }
            }
            Row::Aspect => v.extend(ASPECTS.iter().map(|(n, _)| Some(n.to_string()))),
            Row::Shader => {
                v.push(Some(String::new()));
                v.extend(self.shaders().into_iter().map(Some));
            }
            _ => {}
        }
        v
    }

    fn layer(&self, sys: usize, game: Option<GameRef>) -> Layer {
        match game {
            Some(g) => self.options.game(&self.lib.systems[sys].id, self.lib.path(g)),
            None => self.options.system(&self.lib.systems[sys].id),
        }
    }

    fn row_current(&self, layer: &Layer, row: Row) -> Option<String> {
        match row {
            Row::Emulator => layer.emulator.as_ref().map(|e| format!("{}|{}", e.runner, e.core.clone().unwrap_or_default())),
            Row::Aspect => layer.aspect.clone(),
            Row::Shader => layer.shader.clone(),
            _ => None,
        }
    }

    fn cycle(&mut self, sys: usize, game: Option<GameRef>, row: Row, dir: i32) {
        let values = self.row_values(sys, row);
        let mut layer = self.layer(sys, game);
        let cur = self.row_current(&layer, row);
        let i = values.iter().position(|v| *v == cur).unwrap_or(0) as i32;
        let next = values[((i + dir).rem_euclid(values.len() as i32)) as usize].clone();
        let id = self.lib.systems[sys].id.clone();
        match row {
            Row::Emulator => {
                layer.emulator = next.map(|s| {
                    let (r, c) = s.split_once('|').unwrap();
                    Emulator { runner: r.into(), core: (!c.is_empty()).then(|| c.into()) }
                })
            }
            Row::Aspect => layer.aspect = next,
            Row::Shader => layer.shader = next,
            _ => return,
        }
        let r = match game {
            Some(g) => {
                let path = self.lib.path(g).to_string();
                let field = match row {
                    Row::Emulator => Field::Emulator,
                    Row::Aspect => Field::Aspect,
                    _ => Field::Shader,
                };
                let is_default = self.row_current(&layer, row).is_none();
                if is_default {
                    self.options.clear_game_field(&id, &path, field)
                } else {
                    let s = self.system_of(sys).clone();
                    self.options.set_game(&s, &self.arch, &path, layer)
                }
            }
            None => self.options.set_system(&id, &layer),
        };
        if let Err(e) = r {
            lume_core::log::line("lume-ui", &format!("options not saved: {e}"));
        }
    }

    /// Own options badge: the index flag (set by lume-index) or the options file itself,
    /// which changes before the next scan.
    pub fn has_badge(&self, g: GameRef) -> bool {
        self.lib.has_options(g) || !self.options.game(&self.lib.systems[g.sys].id, self.lib.path(g)).is_empty()
    }

    fn overlay_input(&mut self, ov: Overlay, a: Action, _repeat: bool) -> Option<Overlay> {
        match ov {
            Overlay::Menu { sys, game, mut focus, sub } => {
                let rows = self.menu_rows(sys, game, sub);
                focus = focus.min(rows.len() - 1);
                match a {
                    // B in the Settings submenu goes back to the game menu, on Settings
                    Action::B if sub => return Some(Overlay::Menu { sys, game, focus: 2, sub: false }),
                    Action::B => return None,
                    Action::Up => focus = (focus + rows.len() - 1) % rows.len(),
                    Action::Down => focus = (focus + 1) % rows.len(),
                    Action::Left | Action::Right => {
                        let dir = if a == Action::Left { -1 } else { 1 };
                        if matches!(rows[focus], Row::Emulator | Row::Aspect | Row::Shader) {
                            self.cycle(sys, game, rows[focus], dir);
                        }
                    }
                    Action::A => match rows[focus] {
                        Row::Start => {
                            self.launch(game.unwrap(), None);
                            return None;
                        }
                        Row::StartState => {
                            let g = game.unwrap();
                            let s = self.slots(g);
                            if !s.usable.is_empty() {
                                return Some(Overlay::Slots { game: g, slots: s.usable, focus: 0 });
                            }
                        }
                        Row::Settings => return Some(Overlay::Menu { sys, game, focus: 0, sub: true }),
                        Row::Favorite => {
                            let g = game.unwrap();
                            let on = !self.lib.is_favorite(g);
                            self.set_favorite(g, on);
                            self.toast_key(if on { "added" } else { "removed" });
                            return None;
                        }
                        Row::ClearGames => {
                            let id = self.lib.systems[sys].id.clone();
                            if self.options.clear_games(&id).is_ok() {
                                self.toast_key("cleared");
                            }
                            return None;
                        }
                        Row::Emulator | Row::Aspect | Row::Shader => self.cycle(sys, game, rows[focus], 1),
                    },
                    _ => {}
                }
                Some(Overlay::Menu { sys, game, focus, sub })
            }
            Overlay::Slots { game, slots, mut focus } => {
                match a {
                    Action::B => return Some(Overlay::Menu { sys: game.sys, game: Some(game), focus: 1, sub: false }),
                    Action::Up => focus = (focus + slots.len() - 1) % slots.len(),
                    Action::Down => focus = (focus + 1) % slots.len(),
                    Action::A => {
                        let slot = match slots[focus].as_str() {
                            "auto" => Slot::Auto,
                            n => Slot::N(n.parse().unwrap_or(0)),
                        };
                        self.launch(game, Some(slot));
                        return None;
                    }
                    _ => {}
                }
                Some(Overlay::Slots { game, slots, focus })
            }
            Overlay::Keyboard { mut focus } => {
                let row_len = |r: usize| if r < KEYS.len() { KEYS[r].chars().count() } else { KEY_ACTIONS };
                let (mut r, mut c) = (focus / 16, focus % 16);
                // the D-pad stops at the edges (prototype); B and OK close and keep the text
                match a {
                    Action::Left => c = c.saturating_sub(1),
                    Action::Right => c = (c + 1).min(row_len(r) - 1),
                    Action::Up => r = r.saturating_sub(1),
                    Action::Down => r = (r + 1).min(KEYS.len()),
                    Action::B | Action::Start => {
                        self.close_search();
                        return None;
                    }
                    Action::A => {
                        let g = self.grid.as_mut()?;
                        let full = g.filter.chars().count() >= SEARCH_MAX;
                        if r < KEYS.len() {
                            if !full {
                                g.filter.push(KEYS[r].chars().nth(c).unwrap());
                            }
                        } else {
                            match c {
                                0 if !full => g.filter.push(' '),
                                1 => {
                                    g.filter.pop();
                                }
                                2 => g.filter.clear(),
                                3 => {
                                    self.close_search();
                                    return None;
                                }
                                _ => {}
                            }
                        }
                        self.apply_filter();
                    }
                    _ => {}
                }
                c = c.min(row_len(r) - 1);
                focus = r * 16 + c;
                Some(Overlay::Keyboard { focus })
            }
            Overlay::Confirm { mut focus } => {
                match a {
                    Action::Left | Action::Right | Action::Up | Action::Down => focus ^= 1,
                    Action::B => return None,
                    Action::A => {
                        if focus == 1 {
                            self.exit = Some(Exit::Shutdown);
                        }
                        return None;
                    }
                    _ => {}
                }
                Some(Overlay::Confirm { focus })
            }
        }
    }

    fn set_favorite(&mut self, g: GameRef, on: bool) {
        let ctx = lume_index::Ctx { storage: self.dirs.storage.clone(), catalog: self.catalog.clone(), tile: lume_index::DEFAULT_TILE };
        let id = self.lib.systems[g.sys].id.clone();
        let path = self.lib.path(g).to_string();
        if let Err(e) = lume_index::set_favorite(&ctx, &id, &path, on) {
            lume_core::log::line("lume-ui", &format!("favorite not saved: {e}"));
        }
        self.reload_library();
    }

    fn launch(&mut self, g: GameRef, slot: Option<Slot>) {
        let eff = self.effective(g.sys, Some(g));
        let Some(runner) = self.runner_of(&eff.emulator).cloned() else {
            lume_core::log::line("lume-ui", &format!("runner {} missing", eff.emulator.runner));
            return;
        };
        let id = self.lib.systems[g.sys].id.clone();
        let req = launch::game(&self.dirs, &self.catalog, &runner, &id, self.lib.path(g), &eff, slot);
        match req.write(&self.runtime, false) {
            Ok(()) => self.exit = Some(Exit::Launch),
            Err(e) => lume_core::log::line("lume-ui", &format!("launch file not written: {e}")),
        }
    }

    // ---- settings ----

    pub fn set_rows(&self) -> Vec<SetRow> {
        let mut v = Vec::new();
        if self.sys.wifi_present() {
            v.push(SetRow::Wifi);
        }
        if self.sys.bluetooth_present() {
            v.push(SetRow::Bluetooth);
        }
        v.extend([SetRow::Language, SetRow::Theme, SetRow::Display, SetRow::Volume, SetRow::Brightness, SetRow::System, SetRow::Update, SetRow::RetroArch, SetRow::Power]);
        v
    }

    fn read_levels(&mut self) {
        self.level.clear();
        if let Some(v) = self.sys.volume() {
            self.level.insert("volume", v);
        }
        if let Some(b) = self.sys.brightness() {
            self.level.insert("brightness", b);
        }
    }

    fn save_settings(&mut self) {
        if let Err(e) = self.settings.save(&self.settings_path) {
            lume_core::log::line("lume-ui", &format!("settings not saved: {e}"));
        }
    }

    fn apply_theme(&mut self) {
        self.theme = self.themes.load_or_default(&self.settings.theme);
        for (_, icon) in std::mem::take(&mut self.icons) {
            if let Some((t, _)) = icon {
                self.free_list.push(t);
            }
        }
    }

    /// The Dock icon of a system: icons/<system>.png of the theme or a parent, card first
    /// (only the user's card brings them; the distro has none), decoded once as a mask and
    /// drawn flat in the icon color (as the prototype's logos). The Rect is its size.
    fn icon(&mut self, c: &mut dyn Canvas, id: &str) -> Option<(TextureId, Rect)> {
        if let Some(i) = self.icons.get(id) {
            return *i;
        }
        let made = self
            .themes
            .icon_dirs(&self.theme.id)
            .into_iter()
            .map(|d| d.join(format!("{id}.png")))
            .find(|p| p.is_file())
            .and_then(|p| {
                let (w, h, alpha) = icon_mask(&p, ICON_PX)?;
                let t = c.texture_mask(w, h, &alpha)?;
                Some((t, Rect::new(0, 0, w as i32, h as i32)))
            });
        self.icons.insert(id.to_string(), made);
        made
    }

    fn settings_input(&mut self, a: Action, _repeat: bool) {
        let rows = self.set_rows();
        self.settings_focus = self.settings_focus.min(rows.len() - 1);
        let row = rows[self.settings_focus];
        let dir = match a {
            Action::Left => -1,
            Action::Right => 1,
            _ => 0,
        };
        match a {
            Action::B => self.screen = Screen::Dock,
            // the list wraps: down on the last item goes to the first, up on the first to the last
            Action::Up => self.settings_focus = (self.settings_focus + rows.len() - 1) % rows.len(),
            Action::Down => self.settings_focus = (self.settings_focus + 1) % rows.len(),
            Action::Left | Action::Right => match row {
                SetRow::Language => {
                    let i = LANGUAGES.iter().position(|l| *l == self.settings.language).unwrap_or(0) as i32;
                    let next = LANGUAGES[(i + dir).rem_euclid(LANGUAGES.len() as i32) as usize];
                    self.settings.language = next.into();
                    self.texts = Texts::load(&self.share.join("i18n"), next);
                    self.save_settings();
                    if let Err(e) = crate::system::set_retroarch_language(&self.ra_cfg, lume_core::settings::retroarch_language(next)) {
                        lume_core::log::line("lume-ui", &format!("RetroArch language not saved: {e}"));
                    }
                }
                SetRow::Theme => {
                    let list = self.themes.list();
                    if !list.is_empty() {
                        let current = self.themes.chosen(&self.settings.theme).to_string();
                        let i = list.iter().position(|t| *t == current).unwrap_or(0) as i32;
                        self.settings.theme = list[(i + dir).rem_euclid(list.len() as i32) as usize].clone();
                        self.apply_theme();
                        self.save_settings();
                    }
                }
                SetRow::Display => {
                    self.settings.battery_percent = !self.settings.battery_percent;
                    self.save_settings();
                }
                SetRow::Volume | SetRow::Brightness => {
                    let key = if row == SetRow::Volume { "volume" } else { "brightness" };
                    let cur = self.level.get(key).copied().unwrap_or(50) as i32;
                    let v = (cur + dir * 5).clamp(if row == SetRow::Brightness { 5 } else { 0 }, 100) as u8;
                    self.level.insert(key, v);
                    if row == SetRow::Volume {
                        self.sys.set_volume(v);
                        self.settings.volume = Some(v);
                    } else {
                        self.sys.set_brightness(v);
                        self.settings.brightness = Some(v);
                    }
                    self.save_settings();
                }
                _ => {}
            },
            Action::A => match row {
                SetRow::Update => {
                    self.updating = Some((0, 0));
                    self.start_update = true;
                }
                SetRow::RetroArch => {
                    if let Some(r) = self.runners.get(lume_core::catalog::LIBRETRO_RUNNER) {
                        if launch::retroarch_menu(r).write(&self.runtime, true).is_ok() {
                            self.exit = Some(Exit::RetroArch);
                        }
                    }
                }
                SetRow::Power => self.overlay = Some(Overlay::Confirm { focus: 0 }),
                _ => {}
            },
            _ => {}
        }
    }

    /// Frees the textures the cache let go (call with the canvas before drawing).
    pub fn free_textures(&mut self, c: &mut dyn Canvas) {
        for t in self.free_list.drain(..) {
            c.free_texture(t);
        }
    }

    // ---- drawing ----

    pub fn draw(&mut self, c: &mut dyn Canvas) {
        self.free_textures(c);
        let (w, h) = c.size();
        let th = self.theme.clone();
        c.clear(th.color("bg"));
        c.fill(Rect::new(0, 0, w, h), 0, th.color("bg"));
        // (the search is drawn by the grid itself: bar on top, keyboard below, tiles between)
        match self.screen {
            Screen::Dock => self.draw_dock(c, w, h),
            Screen::Grid => self.draw_grid(c, w, h),
            Screen::Settings => self.draw_settings(c, w, h),
        }
        if let Some(ov) = &self.overlay {
            let ov = match ov {
                Overlay::Menu { sys, game, focus, sub } => Overlay::Menu { sys: *sys, game: *game, focus: *focus, sub: *sub },
                Overlay::Slots { game, slots, focus } => Overlay::Slots { game: *game, slots: slots.clone(), focus: *focus },
                Overlay::Keyboard { focus } => Overlay::Keyboard { focus: *focus },
                Overlay::Confirm { focus } => Overlay::Confirm { focus: *focus },
            };
            self.draw_overlay(c, &ov, w, h);
            // the battery stays in its spot and undimmed over the menus (the search draws it
            // itself, next to its bar); inside its stroke, the dimmed background
            if !matches!(ov, Overlay::Keyboard { .. }) {
                let dimmed = th.color("bg").under(th.color("overlay"));
                self.draw_status_battery_on(c, w, dimmed);
            }
        }
        if let Some((text, _)) = &self.toast {
            let px = (th.em("label_px", w) as f32) * 0.9;
            let tw = c.text_width(text, px).min(w - 32) + 32;
            let r = Rect::new((w - tw) / 2, h - (px as i32) * 3, tw, px as i32 * 2);
            c.fill(r, r.h / 2, th.color("toast_bg"));
            c.text(text, w / 2, r.y + (r.h - px as i32) / 2, px, th.color("toast_fg"), Align::Center, tw - 24);
        }
        if let Some((i, n)) = self.updating {
            let px = th.em("label_px", w) as f32;
            let r = Rect::new(w / 8, h / 2 - px as i32 * 2, w * 3 / 4, px as i32 * 4);
            c.fill(Rect::new(0, 0, w, h), 0, th.color("overlay"));
            c.fill(r, th.em("radius_panel", w), th.color("panel_bg"));
            c.text(&self.tr("updating"), w / 2, r.y + px as i32 / 2, px, th.color("fg"), Align::Center, r.w - 32);
            let bar = Rect::new(r.x + 24, r.bottom() - px as i32, r.w - 48, px as i32 / 3);
            c.fill(bar, bar.h / 2, th.color("tile_bg"));
            if n > 0 {
                c.fill(Rect::new(bar.x, bar.y, bar.w * i as i32 / n as i32, bar.h), bar.h / 2, th.color("accent"));
            }
        }
        if let Some((v, _)) = self.volume_bar.filter(|_| self.screen != Screen::Settings) {
            self.draw_volume_bar(c, w, h, v);
        }
        c.present();
    }

    /// The volume bar (user's choice, 2026-11-15): the whole right edge of the screen as a
    /// line, filled from the bottom with the accent; at 100% the line runs the full height.
    /// No number. A brightness shortcut, when it exists, is the same line on the left edge.
    fn draw_volume_bar(&self, c: &mut dyn Canvas, w: i32, h: i32, v: u8) {
        self.draw_edge_level(c, w, h, v, Edge::Right);
    }

    /// The width of an edge level line (5 px at 640x480).
    fn edge_w(w: i32) -> i32 {
        ((w as f32 / 40.0) * 0.3125).round().max(3.0) as i32
    }

    /// A level as a line along one edge of the screen: a faint track (the muted color at
    /// 30%) the full height, filled from the bottom with the accent.
    fn draw_edge_level(&self, c: &mut dyn Canvas, w: i32, h: i32, v: u8, edge: Edge) {
        let th = &self.theme;
        let lw = Self::edge_w(w);
        let x = match edge {
            Edge::Right => w - lw,
            Edge::Left => 0,
        };
        let mut track = th.color("muted");
        track.a = 77;
        c.fill(Rect::new(x, 0, lw, h), 0, track);
        let filled = h * v.min(100) as i32 / 100;
        if filled > 0 {
            c.fill(Rect::new(x, h - filled, lw, filled), 0, th.color("accent"));
        }
    }

    /// The status bar's battery, in one place on every screen (user's choice, 2026-11-15:
    /// the prototype moved it per screen): the game list's spot, ending 1.75 em from the
    /// right edge with the text's top at 1 em, `status_px`, medium. Returns where it starts.
    fn draw_status_battery(&mut self, c: &mut dyn Canvas, w: i32) -> i32 {
        self.draw_status_battery_on(c, w, self.theme.color("bg"))
    }

    /// The same battery over a background other than `bg` (the dimmed screen under a menu):
    /// `under` is the color inside the icon's stroke.
    fn draw_status_battery_on(&mut self, c: &mut dyn Canvas, w: i32, under: crate::canvas::Color) -> i32 {
        let em = w as f32 / 40.0;
        let px = self.theme.num("status_px") as f32 * em;
        let (right, y) = (w - (1.75 * em).round() as i32, em.round() as i32);
        let mut left = self.draw_battery(c, right, y, px, under);
        // Wi-Fi and Bluetooth, when connected, just left of the battery, in the text color:
        // the prototype's icons 0.9 of the text tall and centered on its line, 0.5 of the text
        // between them and 0.8 before the battery (its gaps in .net and the header)
        let (wifi, bt) = self.network;
        let ih = (px * 0.9).round() as i32;
        let iy = y + ((px * 1.1 - ih as f32) / 2.0).round() as i32;
        let fg = self.theme.color("fg");
        let mut gap = if self.battery.is_some() { (px * 0.8).round() as i32 } else { 0 };
        for (on, key) in [(bt, "@bt"), (wifi, "@wifi")] {
            if !on {
                continue;
            }
            if let Some((t, size)) = self.symbol(c, key) {
                let iw = (ih as f32 * size.w as f32 / size.h as f32).round() as i32;
                left -= gap + iw;
                c.draw_mask(t, Rect::new(left, iy, iw, ih), fg);
                gap = (px * 0.5).round() as i32;
            }
        }
        left
    }

    /// The battery right-aligned at `right` with the text top at `y`, as the prototype: its
    /// SVG icon (a 30x14 box: body 25x12 at (1, 1) with a 1.6 stroke and 2.5 corners, a 2x5
    /// terminal at (27, 4.5), the level in a 20x7 bar at (3.5, 3.5)), all in the text color,
    /// 0.95 of the text tall and centered on its line, 0.35 of the text before the percent
    /// (medium). One color, no charging mark: the prototype has none. Edges are rounded,
    /// not sizes, so the stroke stays even. Returns the x where it starts.
    fn draw_battery(&self, c: &mut dyn Canvas, right: i32, y: i32, px: f32, under: crate::canvas::Color) -> i32 {
        let Some((level, _charging)) = self.battery else { return right };
        let th = &self.theme;
        let fg = th.color("fg");
        let s = px * 0.95 / 14.0; // icon units to pixels
        // the percent (Settings > Display), else the icon alone ends at `right`
        let x0 = if self.settings.battery_percent {
            let label = format!("{level}%");
            let tw = c.text_width_medium(&label, px);
            c.text_medium(&label, right - tw, y, px, fg, Align::Left, tw + 1);
            (right - tw) as f32 - px * 0.35 - 30.0 * s
        } else {
            right as f32 - 29.0 * s
        };
        let y0 = y as f32 + (px * 1.1 - 14.0 * s) / 2.0;
        // a rect from icon units (left, top, right, bottom), its edges rounded
        let rect = |l: f32, t: f32, r: f32, b: f32| {
            let (l, t, r, b) = ((x0 + l * s).round() as i32, (y0 + t * s).round() as i32, (x0 + r * s).round() as i32, (y0 + b * s).round() as i32);
            Rect::new(l, t, (r - l).max(1), (b - t).max(1))
        };
        let rad = |v: f32| (v * s).round() as i32;
        // the stroke: the outer edge, then the inside cut back to the background
        c.fill(rect(0.2, 0.2, 26.8, 13.8), rad(3.3), fg);
        c.fill(rect(1.8, 1.8, 25.2, 12.2), rad(1.7), under);
        c.fill(rect(27.0, 4.5, 29.0, 9.5), rad(1.0), fg);
        let fill = 20.0 * level.min(100) as f32 / 100.0;
        if fill > 0.0 {
            c.fill(rect(3.5, 3.5, 3.5 + fill, 10.5), rad(1.0), fg);
        }
        x0.round() as i32
    }

    fn label(&self, item: DockItem) -> (String, String) {
        match item {
            DockItem::Favorites => (self.tr("favorites"), self.tr("dock_favorites")),
            DockItem::Recent => (self.tr("recent"), self.tr("dock_recent")),
            DockItem::Settings => (self.tr("settings"), self.tr("dock_settings")),
            DockItem::System(s) => (self.lib.systems[s].name.clone(), self.lib.systems[s].abbr.clone()),
        }
    }

    /// The Dock, measured on the prototype at 640x480 (1 em = 16 px): icons `icon` em at
    /// rest, magnified by a gaussian (`mag_*`: 10.8, 8.13 and 5.09 em next to the focus,
    /// 4.32 em further), `dock_gap` em apart; each icon passes at `dock_origin` of its height
    /// through the line at `dock_top` of the screen (201.6 px), so a larger icon rises; the
    /// corner radius and the content grow with the icon (the abbreviation 0.28 of it, bold;
    /// a logo 78% x 56%; the star 0.42; the gear 0.2). The name (`dock_name_px`) 6.54 em under
    /// that line, its subtitle (`dock_sub_px`, muted) 2.62 em lower; the battery 1.08 em from
    /// the right edge at 0.51 em; the hints ◀▶ Navigate, A Select.
    fn draw_dock(&mut self, c: &mut dyn Canvas, w: i32, h: i32) {
        let th = &self.theme.clone();
        let n = self.dock.len() as i32;
        let em = w as f32 / 40.0;
        let base = th.num("icon") as f32 * em;
        let gap = th.num("dock_gap") as f32 * em;
        let line = h as f32 * th.num("dock_top") as f32;
        let origin = th.num("dock_origin") as f32;
        let (peak, low, spread) = (th.num("mag_peak") as f32, th.num("mag_base") as f32, th.num("mag_spread") as f32);
        // the prototype's Dock motion: cubic-bezier(.22, 1.25, .36, 1) over `anim_ms` (0.2 s),
        // a light spring that passes the mark a little and settles
        let shift = match self.anim {
            Some((t, from)) => {
                let k = (t.elapsed().as_secs_f32() * 1000.0 / th.num("anim_ms").max(1.0) as f32).min(1.0);
                from * (1.0 - cubic_bezier(0.22, 1.25, 0.36, 1.0, k))
            }
            None => 0.0,
        };
        let scale = |d: f32| low + (peak - low) * (-(d * d) / (2.0 * spread * spread)).exp();
        // items at offsets -k..k around the focus, wrapping (only the visible ones are drawn)
        let reach = 4;
        let mut items = Vec::new();
        for off in -reach..=reach {
            if n < 2 * reach + 1 && (off < -(n / 2) || off > (n - 1) / 2) {
                continue;
            }
            let idx = ((self.dock_focus as i32 + off).rem_euclid(n)) as usize;
            items.push((off as f32 + shift, idx));
        }
        // x of each item from the center: the sizes and gaps in between, step by step
        let mut placed: Vec<(f32, f32, usize)> = Vec::new();
        for (d, idx) in &items {
            let (mut x, mut at) = (0.0f32, 0.0f32);
            while at < d.abs() {
                let next = (at + 1.0).min(d.abs());
                x += ((scale(at) + scale(next)) / 2.0 * base + gap) * (next - at);
                at = next;
            }
            placed.push((if *d < 0.0 { -x } else { x }, scale(*d) * base, *idx));
        }
        // the focused (largest) icon is drawn last, over its neighbors
        placed.sort_by(|a, b| a.1.partial_cmp(&b.1).unwrap());
        // while the volume line shows on the right edge, the icons stop `dock_gap` before it
        // (user's request: the console on the right never touches the line)
        let volume_on = self.volume_bar.is_some();
        if volume_on {
            c.set_clip(Some(Rect::new(0, 0, w - Self::edge_w(w) - gap.round() as i32, h)));
        }
        for (x, size, idx) in placed {
            let left = w as f32 / 2.0 + x - size / 2.0;
            let top = line - size * origin;
            let r = Rect::new(left.round() as i32, top.round() as i32, size.round() as i32, size.round() as i32);
            if r.right() < 0 || r.x > w {
                continue;
            }
            let focused = idx == self.dock_focus;
            let (bg, fg) = if focused { (th.color("icon_sel_bg"), th.color("icon_sel_fg")) } else { (th.color("icon_bg"), th.color("icon_fg")) };
            c.fill(r, (th.num("radius_icon") as f32 * em * size / base).round() as i32, bg);
            // the content of the icon: a card logo, a symbol of the launcher, or the abbreviation
            let (key, share, lift) = match self.dock[idx] {
                DockItem::System(s) => (self.lib.systems[s].id.clone(), 0.0, 0.0),
                DockItem::Favorites => ("@star".to_string(), 0.42, 0.01),
                DockItem::Settings => ("@gear".to_string(), 0.2, 0.0),
                DockItem::Recent => ("@clock".to_string(), 0.3, 0.0),
            };
            let icon = if share > 0.0 { self.symbol(c, &key) } else { self.icon(c, &key) };
            match icon {
                Some((t, isz)) if share > 0.0 => {
                    let d = (size * share).round() as i32;
                    let cy = r.y as f32 + r.h as f32 * (0.5 - lift);
                    c.draw_mask(t, Rect::new(r.x + (r.w - d) / 2, (cy - d as f32 / 2.0).round() as i32, d, d * isz.h / isz.w.max(1)), fg);
                }
                Some((t, isz)) => {
                    // the logo fits 78% x 56% of the tile (prototype), flat in the icon color
                    let (bw, bh) = (r.w as f64 * 0.78, r.h as f64 * 0.56);
                    let k = f64::min(bw / isz.w as f64, bh / isz.h as f64);
                    let (dw, dh) = ((isz.w as f64 * k) as i32, (isz.h as f64 * k) as i32);
                    c.draw_mask(t, Rect::new(r.x + (r.w - dw) / 2, r.y + (r.h - dh) / 2, dw, dh), fg);
                }
                None => {
                    let (_, abbr) = self.label(self.dock[idx]);
                    let px = (size * 0.28).max(8.0);
                    c.text_bold(&abbr, r.x + r.w / 2, r.y + (r.h - px as i32) / 2, px, fg, Align::Center, r.w - 8);
                }
            }
        }
        if volume_on {
            c.set_clip(None);
        }
        // the focused item's name and what it holds
        let (name, _) = self.label(self.dock[self.dock_focus]);
        let name_px = th.num("dock_name_px") as f32 * em;
        let sub_px = th.num("dock_sub_px") as f32 * em;
        let name_y = (line + 6.544 * em).round() as i32;
        c.text(&name, w / 2, name_y, name_px, th.color("fg"), Align::Center, w - 2 * em as i32);
        let sub = match self.dock[self.dock_focus] {
            DockItem::System(s) => format!("{} {}", self.lib.systems[s].index.len(), self.tr("games")),
            DockItem::Favorites => format!("{} {}", self.lib.favorites().len(), self.tr("games")),
            DockItem::Recent => format!("{} {}", self.lib.recents(RECENT_MAX).len(), self.tr("games")),
            DockItem::Settings => self.tr("dock_settings_sub"),
        };
        c.text(&sub, w / 2, name_y + (2.62 * em).round() as i32, sub_px, th.color("muted"), Align::Center, w - 2 * em as i32);
        // status bar: the battery at the top right (regular weight here, as the prototype)
        self.draw_status_battery(c, w);
        self.draw_hints(c, w, h, &[(NAV_LR, self.tr("hint_navigate")), ("A", self.tr("hint_select"))]);
    }

    /// A symbol of the launcher (`@star`, `@gear`, `@clock`) as a mask texture, made once.
    fn symbol(&mut self, c: &mut dyn Canvas, key: &str) -> Option<(TextureId, Rect)> {
        if let Some(i) = self.icons.get(key) {
            return *i;
        }
        const N: u32 = 128;
        let (w, h, alpha) = match key {
            "@star" => (N, N, crate::glyphs::star(N)),
            "@gear" => (N, N, crate::glyphs::gear(N)),
            "@check" => (N, N, crate::glyphs::check(N)),
            // the status bar's icons, drawn about 17 px tall: made at 3x, scaled down
            "@wifi" => crate::glyphs::wifi(56),
            "@bt" => crate::glyphs::bluetooth(56),
            _ => (N, N, crate::glyphs::clock(N)),
        };
        let made = c.texture_mask(w, h, &alpha).map(|t| (t, Rect::new(0, 0, w as i32, h as i32)));
        self.icons.insert(key.to_string(), made);
        made
    }

    /// The button hints, as the prototype at 640x480 (1 em = 16 px): a band of 2.4 em at the
    /// bottom, centered as a whole; each hint is a 1.48 em circle in the accent with its
    /// letter bold (0.85 of the text), 0.36 em, then the text (`hint_px`, muted); 1.44 em
    /// between hints.
    fn draw_hints(&self, c: &mut dyn Canvas, w: i32, h: i32, hints: &[(&str, String)]) {
        let th = &self.theme;
        let em = w as f32 / 40.0;
        let px = th.num("hint_px") as f32 * em;
        let d = (1.48 * em).round() as i32;
        let lpx = px * 0.85;
        let inner = (0.36 * em).round() as i32;
        let between = (1.44 * em).round() as i32;
        let chip_y = h - (1.9 * em).round() as i32;
        // the text line starts 1.97 em from the bottom (448.5 at 480, measured)
        let ty = h - (1.97 * em).round() as i32;
        // the arrows' chips are wider (◀▶ 2.45 em, ▲▼ 2.64 em) and tonal (`nav_bg`, `nav_fg`)
        let nav_lr = (2.45 * em).round() as i32;
        let nav_ud = (2.64 * em).round() as i32;
        let chip_w = |btn: &str| match btn {
            "" => 0,
            NAV_LR => nav_lr,
            NAV_UD => nav_ud,
            _ => d,
        };
        let widths: Vec<i32> = hints.iter().map(|(btn, text)| c.text_width(text, px) + if btn.is_empty() { 0 } else { chip_w(btn) + inner }).collect();
        let total = widths.iter().sum::<i32>() + between * (hints.len() as i32 - 1).max(0);
        let mut x = (w - total) / 2;
        for ((btn, text), hw) in hints.iter().zip(&widths) {
            let mut tx = x;
            if *btn == NAV_LR || *btn == NAV_UD {
                let nav_w = chip_w(btn);
                c.fill(Rect::new(x, chip_y, nav_w, d), d / 2, th.color("nav_bg"));
                let (cx, cy) = (x + nav_w / 2, chip_y + d / 2);
                // two separate triangles, tips out (as ◀▶ in the prototype's font)
                let (tw, tht) = ((d as f32 * 0.42).round() as i32, (d as f32 * 0.55).round() as i32);
                let sep = (d / 8).max(2);
                let fg = th.color("nav_fg");
                if *btn == NAV_LR {
                    triangle(c, cx - sep / 2 - tw / 2, cy, tw, tht, Dir::Left, fg);
                    triangle(c, cx + sep / 2 + tw / 2, cy, tw, tht, Dir::Right, fg);
                } else {
                    triangle(c, cx - sep / 2 - tht / 2, cy, tht, tw, Dir::Up, fg);
                    triangle(c, cx + sep / 2 + tht / 2, cy, tht, tw, Dir::Down, fg);
                }
                tx += nav_w + inner;
            } else if !btn.is_empty() {
                c.fill(Rect::new(x, chip_y, d, d), d / 2, th.color("accent"));
                // centered by Roboto's line height (1.172 of the size), as the browser does
                c.text_bold(btn, x + d / 2, chip_y + ((d as f32 - lpx * 1.172) / 2.0).round() as i32, lpx, th.color("accent_fg"), Align::Center, d);
                tx += d + inner;
            }
            let tw = c.text_width(text, px);
            c.text(text, tx, ty, px, th.color("muted"), Align::Left, tw + 1);
            x += hw + between;
        }
    }

    fn list_title(&self, k: ListKind) -> String {
        match k {
            ListKind::Favorites => self.tr("favorites"),
            ListKind::Recent => self.tr("recent"),
            ListKind::System(s) => self.lib.systems[s].name.clone(),
        }
    }

    /// The game list, measured on the prototype at 640x480 (1 em = 16 px, w / 40):
    /// - header band 3.325 em: the list name (`list_title_px`, bold) at (1.75 em, 0.7 em), the
    ///   counter in the middle and the battery ending 1.75 em from the right, both at 1 em
    ///   (`status_px`);
    /// - tiles from (1 em, 3.525 em), 0.7 em apart, down to 0.4 em above the name band; the
    ///   cover only, 0.4 em inside its tile; the focused tile 3% larger with a 0.2 em accent
    ///   outline 0.05 em away;
    /// - the focused game's name centered in a 2.106 em band (`list_name_px`) above the hints
    ///   band (2.394 em).
    ///
    /// While searching (TV launcher style) the header band is the search bar, the keyboard
    /// sits above the hints, and the tiles that are left fill the space between, filtered as
    /// the user types.
    fn draw_grid(&mut self, c: &mut dyn Canvas, w: i32, h: i32) {
        let th = self.theme.clone();
        let Some(kind) = self.grid.as_ref().map(|g| g.kind) else { return };
        let kb = match &self.overlay {
            Some(Overlay::Keyboard { focus }) => Some(*focus),
            _ => None,
        };
        let em = w as f32 / 40.0;
        let e = |v: f32| (v * em).round() as i32;
        let title_px = th.num("list_title_px") as f32 * em;
        let status_px = th.num("status_px") as f32 * em;
        let name_px = th.num("list_name_px") as f32 * em;
        let hints_top = h - e(2.394);
        let kb_rect = kb.map(|_| self.keyboard_rect(w, hints_top));
        let name_top = kb_rect.map_or(hints_top, |r| r.y) - e(2.106);
        let top = e(3.525);
        let bottom = name_top - e(0.4);
        let cols = th.num("cols").max(1.0) as i32;
        // positions in fractions of a pixel, rounded only when drawn: the prototype's 143.6 px
        // tiles 11.2 px apart would drift a pixel per column otherwise
        let gap = 0.7 * em;
        let tile_w = (w as f32 - 2.0 * em - (cols - 1) as f32 * gap) / cols as f32;
        let avail = (bottom - top) as f32;
        // a taller screen gets more rows (spec: layout independent of the resolution), each
        // tile at least as tall as wide (a box is portrait); the search keeps what fits
        let min_rows = if kb.is_some() { 1 } else { th.num("rows") as i32 };
        let rows = min_rows.max((avail / (tile_w + gap)) as i32).max(1);
        let tile_h = (avail - (rows - 1) as f32 * gap) / rows as f32;
        let cell = |col: i32, row: i32| {
            let (x0, y0) = (em + col as f32 * (tile_w + gap), top as f32 + row as f32 * (tile_h + gap));
            let (x, y) = (x0.round() as i32, y0.round() as i32);
            Rect::new(x, y, (x0 + tile_w).round() as i32 - x, (y0 + tile_h).round() as i32 - y)
        };
        self.cols = cols as usize;
        self.rows = rows as usize;
        self.scroll_to_focus();
        let title = self.list_title(kind);
        let g = self.grid.as_ref().unwrap();
        let (filter, items, focus, gtop) = (g.filter.clone(), g.items.clone(), g.focus, g.top);
        if kb.is_some() {
            self.draw_search_bar(c, w, &filter, items.len());
        } else {
            // header: the list name on the left, the counter in the middle, the battery right
            // and, with a filter on, the filter just left of the battery
            let count = if items.is_empty() { String::new() } else { format!("{} / {}", focus + 1, items.len()) };
            let cw = c.text_width_medium(&count, status_px);
            let batt_x = self.draw_status_battery(c, w);
            if !filter.is_empty() {
                let right = if batt_x < w - e(1.75) { batt_x - e(1.0) } else { w - e(1.75) };
                c.text(&format!("“{filter}”"), right, e(1.0), status_px, th.color("accent"), Align::Right, right - w / 2 - cw / 2 - e(1.0));
            }
            c.text_bold(&title, e(1.75), e(0.7), title_px, th.color("fg"), Align::Left, w / 2 - cw / 2 - e(2.75));
            if !items.is_empty() {
                c.text_medium(&count, w / 2, e(1.0), status_px, th.color("muted"), Align::Center, cw + 1);
            }
        }
        if items.is_empty() {
            let key = if !filter.is_empty() {
                "no_results"
            } else if kind == ListKind::Favorites {
                "no_favorites"
            } else {
                "no_recent"
            };
            c.text(&self.tr(key), w / 2, (top + bottom) / 2 - status_px as i32 / 2, status_px, th.color("muted"), Align::Center, w - 2 * e(1.0));
        }
        let first = gtop * cols as usize;
        let radius = th.em("radius_tile", w);
        let pad = 0.4 * em;
        for (k, r) in items.iter().enumerate().skip(first).take((cols * rows) as usize) {
            let pos = (k - first) as i32;
            let focused = k == focus && kb.is_none();
            let mut tile = cell(pos % cols, pos / cols);
            let mut pad_px = pad;
            if focused {
                // 3% larger around its center, then the outline 0.05 em away, 0.2 em wide
                let (cx, cy) = (tile.x as f32 + tile.w as f32 / 2.0, tile.y as f32 + tile.h as f32 / 2.0);
                let (sw, sh) = (tile_w * 1.03, tile_h * 1.03);
                tile = Rect::new((cx - sw / 2.0).round() as i32, (cy - sh / 2.0).round() as i32, sw.round() as i32, sh.round() as i32);
                pad_px *= 1.03;
                let (off, ring) = (e(0.05).max(1), e(0.2).max(2));
                c.fill(tile.inset(-(off + ring)), radius + off + ring, th.color("accent"));
                c.fill(tile.inset(-off), radius + off, th.color("bg"));
                c.fill(tile, radius, th.color("tile_bg_sel"));
            } else {
                c.fill(tile, radius, th.color("tile_bg"));
            }
            let art = tile.inset(pad_px.round() as i32);
            match self.texture(c, *r) {
                Some((t, src)) => {
                    // only the cover: it keeps its shape, centered in the tile
                    let k = f64::min(art.w as f64 / src.w as f64, art.h as f64 / src.h as f64);
                    let (dw, dh) = ((src.w as f64 * k) as i32, (src.h as f64 * k) as i32);
                    c.draw_texture(t, src, Rect::new(art.x + (art.w - dw) / 2, art.y + (art.h - dh) / 2, dw, dh));
                }
                None => {
                    // no cover: the generated box, with the name on it
                    let name = self.lib.name(*r).to_string();
                    c.fill(art, radius / 2, th.color("icon_bg"));
                    c.text(&name, art.x + art.w / 2, art.y + art.h / 2 - status_px as i32 / 2, status_px, th.color("icon_fg"), Align::Center, art.w - 8);
                }
            }
            if self.has_badge(*r) {
                c.fill(Rect::new(tile.right() - e(1.0), tile.y + e(0.5), e(0.6), e(0.6)), e(0.3), th.color("accent"));
            }
            if self.lib.is_favorite(*r) && kind != ListKind::Favorites {
                // favorite: a dot in the text color, top left (the options badge is top right)
                c.fill(Rect::new(tile.x + e(0.4), tile.y + e(0.5), e(0.6), e(0.6)), e(0.3), th.color("fg"));
            }
        }
        // the focused game's name, centered in its band above the hints (or the keyboard)
        if let Some(r) = items.get(focus) {
            let name = self.lib.name(*r).to_string();
            // the band's top padding is 0.15 of the font (prototype)
            c.text_medium(&name, w / 2, name_top + (name_px * 0.15).round() as i32, name_px, th.color("fg"), Align::Center, w - 2 * e(1.0));
        }
        if let (Some(f), Some(r)) = (kb, kb_rect) {
            self.draw_keyboard(c, r, f, w);
            self.draw_hints(c, w, h, &[("A", self.tr("hint_select")), ("B", self.tr("hint_close"))]);
            return;
        }
        // the prototype's order: A, X, Y, B
        let mut hints = vec![("A", self.tr("hint_select")), ("X", self.tr("hint_search"))];
        if matches!(kind, ListKind::System(_)) {
            hints.push(("Y", self.tr("hint_options")));
        }
        hints.push(("B", self.tr("hint_back")));
        self.draw_hints(c, w, h, &hints);
    }

    /// The search keyboard's place: the full width, ending at the hints band.
    fn keyboard_rect(&self, w: i32, hints_top: i32) -> Rect {
        let em = w as f32 / 40.0;
        let (key_h, gap, pad) = ((1.6 * em).round() as i32, (0.25 * em).round() as i32, (0.5 * em).round() as i32);
        let rows = KEYS.len() as i32 + 1;
        let kh = rows * key_h + (rows - 1) * gap + 2 * pad;
        Rect::new(0, hints_top - kh, w, kh)
    }

    /// The search bar in the header band: the typed text with a cursor, the live count.
    fn draw_search_bar(&mut self, c: &mut dyn Canvas, w: i32, text: &str, count: usize) {
        let th = self.theme.clone();
        let em = w as f32 / 40.0;
        let e = |v: f32| (v * em).round() as i32;
        let field_px = th.num("list_name_px") as f32 * em;
        let status_px = th.num("status_px") as f32 * em;
        // the battery keeps its spot; the bar ends 1 em before it (the whole width without one)
        let batt_x = self.draw_status_battery(c, w);
        let right = if batt_x < w - e(1.75) { batt_x - e(1.0) } else { w - e(1.0) };
        let field = Rect::new(e(1.0), e(0.5), right - e(1.0), e(2.4));
        c.fill(field, th.em("radius_item", w).min(field.h / 2), th.color("panel_bg_opaque"));
        let count_txt = format!("{count} {}", self.tr("games"));
        let cw = c.text_width(&count_txt, status_px);
        c.text(&count_txt, field.right() - e(1.0), field.y + (field.h - status_px as i32) / 2, status_px, th.color("muted"), Align::Right, cw + 1);
        let room = field.w - e(3.0) - cw;
        // the end of a long text stays visible
        let mut shown: &str = text;
        while !shown.is_empty() && c.text_width(shown, field_px) > room {
            let next = shown.char_indices().nth(1).map_or(shown.len(), |(i, _)| i);
            shown = &shown[next..];
        }
        let tx = field.x + e(1.0);
        let ty = field.y + (field.h - field_px as i32) / 2;
        let tw = if shown.is_empty() { 0 } else { c.text(shown, tx, ty, field_px, th.color("fg"), Align::Left, room) };
        c.fill(Rect::new(tx + tw + 2, ty + 2, (field_px / 12.0).max(2.0) as i32, field_px as i32), 0, th.color("accent"));
    }

    /// The on-screen keyboard (QWERTY with numbers, then space, backspace, clear and OK) in
    /// `r`, on its own panel.
    fn draw_keyboard(&mut self, c: &mut dyn Canvas, r: Rect, focus: usize, w: i32) {
        let th = self.theme.clone();
        let em = w as f32 / 40.0;
        let e = |v: f32| (v * em).round() as i32;
        let (key_h, gap, pad) = (e(1.6), e(0.25), e(0.5));
        let px = th.num("status_px") as f32 * em;
        // the panel a step darker than the keys, in every theme
        c.fill(r, 0, th.color("tile_bg_opaque"));
        let key_w = (w - 2 * e(1.0) - 9 * gap) / 10;
        let (fr, fc) = (focus / 16, focus % 16);
        let radius = th.em("radius_item", w).min(key_h / 2);
        let key = |c: &mut dyn Canvas, k: Rect, label: &str, sel: bool| {
            c.fill(k, radius, th.color(if sel { "sel_bg" } else { "tile_bg_sel" }));
            c.text(label, k.x + k.w / 2, k.y + (k.h - px as i32) / 2, px, th.color(if sel { "sel_fg" } else { "fg" }), Align::Center, k.w - 4);
        };
        for (ri, row) in KEYS.iter().enumerate() {
            let n = row.chars().count() as i32;
            let x0 = (w - (n * key_w + (n - 1) * gap)) / 2;
            let y = r.y + pad + ri as i32 * (key_h + gap);
            for (ci, ch) in row.chars().enumerate() {
                key(c, Rect::new(x0 + ci as i32 * (key_w + gap), y, key_w, key_h), &ch.to_string(), ri == fr && ci == fc);
            }
        }
        // backspace has no label: the bundled font has no ⌫ (nor ←), so it is drawn
        let labels = [self.tr("key_space"), String::new(), self.tr("key_clear"), self.tr("key_done")];
        let widths: Vec<i32> = labels.iter().map(|l| (c.text_width(l, px) + key_w).max(key_w * 3 / 2)).collect();
        let total: i32 = widths.iter().sum::<i32>() + gap * (widths.len() as i32 - 1);
        let mut x = (w - total) / 2;
        let y = r.y + pad + KEYS.len() as i32 * (key_h + gap);
        for (ci, l) in labels.iter().enumerate() {
            let sel = fr == KEYS.len() && fc == ci;
            let k = Rect::new(x, y, widths[ci], key_h);
            key(c, k, l, sel);
            if ci == 1 {
                back_icon(c, k.x + k.w / 2, k.y + k.h / 2, (px * 0.8) as i32, th.color(if sel { "sel_fg" } else { "fg" }));
            }
            x += widths[ci] + gap;
        }
    }

    /// The texture of a cover and its image part, from the LRU (made from the mapped slot
    /// when missing).
    fn texture(&mut self, c: &mut dyn Canvas, r: GameRef) -> Option<(TextureId, Rect)> {
        if let Some(t) = self.thumbs.get(&r) {
            return Some(*t);
        }
        let s = self.lib.thumb(r)?;
        let (tw, th) = (s.tile.w as i32, s.tile.h as i32);
        let (cw, ch) = (s.content.0.max(1) as i32, s.content.1.max(1) as i32);
        let src = Rect::new((tw - cw) / 2, (th - ch) / 2, cw, ch);
        let t = c.texture_rgb565(tw as u32, th as u32, s.pixels)?;
        for (old, _) in self.thumbs.insert(r, (t, src), s.tile.pixel_bytes()) {
            c.free_texture(old);
        }
        Some((t, src))
    }

    pub fn thumb_bytes(&self) -> usize {
        self.thumbs.used()
    }

    fn draw_panel(&self, c: &mut dyn Canvas, w: i32, h: i32, rows: &[(String, String, bool)], focus: usize, title: &str) -> Rect {
        let th = &self.theme;
        let px = th.em("label_px", w) as f32;
        let row_h = (px * 1.9) as i32;
        let pw = (w * 7 / 8).min(w - 32);
        let ph = (row_h * rows.len() as i32 + (px * 2.6) as i32).min(h - 32);
        let r = Rect::new((w - pw) / 2, (h - ph) / 2, pw, ph);
        c.fill(Rect::new(0, 0, w, h), 0, th.color("overlay"));
        c.fill(r, th.em("radius_panel", w), th.color("panel_bg"));
        c.text(title, r.x + 24, r.y + (px * 0.6) as i32, px, th.color("muted"), Align::Left, r.w - 48);
        let first = (focus as i32 - ((ph - (px * 2.6) as i32) / row_h - 1)).max(0) as usize;
        for (i, (label, value, enabled)) in rows.iter().enumerate().skip(first) {
            let y = r.y + (px * 2.2) as i32 + (i - first) as i32 * row_h;
            if y + row_h > r.bottom() {
                break;
            }
            let row = Rect::new(r.x + 12, y, r.w - 24, row_h - 4);
            let fg = if i == focus {
                c.fill(row, th.em("radius_item", w).min(row.h / 2), th.color("sel_bg"));
                th.color("sel_fg")
            } else if *enabled {
                th.color("fg")
            } else {
                th.color("muted")
            };
            let ty = row.y + (row.h - px as i32) / 2;
            let vw = if value.is_empty() { 0 } else { c.text_width(value, px * 0.9).min(row.w / 2) };
            c.text(label, row.x + 16, ty, px, fg, Align::Left, row.w - 40 - vw);
            if !value.is_empty() {
                c.text(value, row.right() - 16, ty, px * 0.9, if i == focus { fg } else { th.color("muted") }, Align::Right, row.w / 2);
            }
        }
        r
    }

    fn row_value(&self, sys: usize, game: Option<GameRef>, row: Row) -> String {
        let layer = self.layer(sys, game);
        let eff = self.effective(sys, game);
        let own = self.row_current(&layer, row).is_some();
        let v = match row {
            Row::Emulator => launch::emulator_label(&eff.emulator),
            Row::Aspect => match eff.aspect.as_deref() {
                None => self.tr("default"),
                Some("core") => self.tr("aspect_core"),
                Some("square") => self.tr("aspect_square"),
                Some("full") => self.tr("aspect_full"),
                Some(a) => a.to_string(),
            },
            Row::Shader => match eff.shader.as_deref() {
                None => self.tr("default"),
                Some("") => self.tr("shader_none"),
                Some(s) => std::path::Path::new(s).file_stem().map(|f| f.to_string_lossy().into_owned()).unwrap_or_default(),
            },
            _ => String::new(),
        };
        if own || row != Row::Emulator {
            format!("‹{v} ›")
        } else {
            format!("‹{v} · {} ›", self.tr("default"))
        }
    }

    fn draw_overlay(&mut self, c: &mut dyn Canvas, ov: &Overlay, w: i32, h: i32) {
        match ov {
            Overlay::Menu { sys, game, focus, sub } => {
                let rows = self.menu_rows(*sys, *game, *sub);
                let mut out = Vec::new();
                for row in &rows {
                    out.push(match row {
                        Row::Start => (self.tr("start"), String::new(), true),
                        Row::Settings => (self.tr("settings"), String::new(), true),
                        Row::StartState => {
                            let s = self.slots(game.unwrap());
                            let v = if !s.usable.is_empty() {
                                s.usable.len().to_string()
                            } else if s.other_core > 0 {
                                self.texts.n("other_core", s.other_core)
                            } else {
                                self.tr("no_states")
                            };
                            (self.tr("start_state"), v, !s.usable.is_empty())
                        }
                        Row::Emulator => (self.tr("emulator"), self.row_value(*sys, *game, *row), true),
                        Row::Aspect => (self.tr("aspect"), self.row_value(*sys, *game, *row), true),
                        Row::Shader => (self.tr("shader"), self.row_value(*sys, *game, *row), true),
                        Row::Favorite => (self.tr(if self.lib.is_favorite(game.unwrap()) { "fav_del" } else { "fav_add" }), String::new(), true),
                        Row::ClearGames => (self.tr("clear_games"), String::new(), true),
                    });
                }
                let title = match game {
                    Some(g) if *sub => format!("{} · {}", self.lib.name(*g), self.tr("settings")),
                    Some(g) => self.lib.name(*g).to_string(),
                    None => format!("{} · {}", self.lib.systems[*sys].name, self.tr("console_options")),
                };
                self.draw_panel(c, w, h, &out, *focus, &title);
            }
            Overlay::Slots { game, slots, focus } => self.draw_slots(c, *game, slots, *focus, w, h),
            Overlay::Keyboard { .. } => {}
            Overlay::Confirm { focus } => {
                let rows = vec![(self.tr("cancel"), String::new(), true), (self.tr("power_off"), String::new(), true)];
                let title = self.tr("power_ask");
                self.draw_panel(c, w, h, &rows, *focus, &title);
            }
        }
    }

    /// The save states of a game: the slots on the left, the picture RetroArch saved with the
    /// focused one on the right (savestate_thumbnail_enable), or a note when there is none.
    fn draw_slots(&mut self, c: &mut dyn Canvas, game: GameRef, slots: &[String], focus: usize, w: i32, h: i32) {
        let th = self.theme.clone();
        let px = th.em("label_px", w) as f32;
        let margin = w / 40;
        let row_h = (px * 1.9) as i32;
        // below the header band (3.325 em, the list's: the battery stays in sight) and 0.4 em
        // above the hints band, as the Settings panel
        let em = w as f32 / 40.0;
        let top = (3.325 * em).round() as i32;
        let bottom = h - (2.394 * em).round() as i32 - (0.4 * em).round() as i32;
        let panel = Rect::new(margin, top, w - 2 * margin, bottom - top);
        c.fill(Rect::new(0, 0, w, h), 0, th.color("overlay"));
        c.fill(panel, th.em("radius_panel", w), th.color("panel_bg"));
        let title = format!("{} · {}", self.lib.name(game), self.tr("start_state"));
        c.text(&title, panel.x + 24, panel.y + (px * 0.6) as i32, px, th.color("muted"), Align::Left, panel.w - 48);
        let top = panel.y + (px * 2.2) as i32;
        let list = Rect::new(panel.x + 12, top, panel.w * 2 / 5 - 12, panel.bottom() - top - 12);
        let visible = (list.h / row_h).max(1) as usize;
        let first = focus.saturating_sub(visible - 1);
        for (i, s) in slots.iter().enumerate().skip(first).take(visible) {
            let row = Rect::new(list.x, list.y + (i - first) as i32 * row_h, list.w, row_h - 4);
            let fg = if i == focus {
                c.fill(row, th.em("radius_item", w).min(row.h / 2), th.color("sel_bg"));
                th.color("sel_fg")
            } else {
                th.color("fg")
            };
            let label = if s == "auto" { self.tr("slot_auto") } else { self.texts.n("slot", s) };
            c.text(&label, row.x + 16, row.y + (row.h - px as i32) / 2, px, fg, Align::Left, row.w - 24);
        }
        // the picture of the focused slot, kept in its shape
        let pic = Rect::new(list.right() + margin, top, panel.right() - 12 - list.right() - margin, list.h);
        c.fill(pic, th.em("radius_tile", w), th.color("tile_bg_opaque"));
        match slots.get(focus).and_then(|s| self.slot_picture(c, game, s)) {
            Some((t, src)) => {
                let area = pic.inset(6);
                let k = f64::min(area.w as f64 / src.w as f64, area.h as f64 / src.h as f64);
                let (dw, dh) = ((src.w as f64 * k) as i32, (src.h as f64 * k) as i32);
                c.draw_texture(t, src, Rect::new(area.x + (area.w - dw) / 2, area.y + (area.h - dh) / 2, dw, dh));
            }
            None => {
                c.text(&self.tr("no_picture"), pic.x + pic.w / 2, pic.y + (pic.h - px as i32) / 2, px * 0.9, th.color("muted"), Align::Center, pic.w - 16);
            }
        }
    }

    /// The picture of one save state slot (`<state file>.png`), decoded once per slot shown;
    /// the previous one is freed.
    fn slot_picture(&mut self, c: &mut dyn Canvas, game: GameRef, slot: &str) -> Option<(TextureId, Rect)> {
        let rom = self.dirs.rom(&self.lib.systems[game.sys].id, self.lib.path(game));
        let path = launch::state_picture(&self.dirs.states_prefix(&rom), slot);
        if let Some((p, pic)) = &self.slot_pic {
            if *p == path {
                return *pic;
            }
        }
        if let Some((_, Some((t, _)))) = self.slot_pic.take() {
            c.free_texture(t);
        }
        let tile = lume_index::thumbs::Tile { w: 320, h: 240 };
        let pic = lume_index::thumbs::render(&path, tile).and_then(|px| {
            let (cw, ch) = (u16::from_le_bytes([px[0], px[1]]) as i32, u16::from_le_bytes([px[2], px[3]]) as i32);
            let t = c.texture_rgb565(tile.w as u32, tile.h as u32, &px[4..])?;
            Some((t, Rect::new((tile.w as i32 - cw) / 2, (tile.h as i32 - ch) / 2, cw.max(1), ch.max(1))))
        });
        self.slot_pic = Some((path, pic));
        pic
    }

    pub fn set_row_texts(&self, row: SetRow) -> (String, String) {
        let pct = |k: &str| self.level.get(k).map(|v| format!("‹{v}% ›")).unwrap_or_else(|| "—".into());
        match row {
            SetRow::Wifi => (self.tr("wifi"), self.sys.wifi_connected().map(|s| format!("{}: {s}", self.tr("connected"))).unwrap_or_else(|| self.tr("disconnected"))),
            SetRow::Bluetooth => (self.tr("bluetooth"), self.sys.bluetooth_connected().map(|s| format!("{}: {s}", self.tr("connected"))).unwrap_or_else(|| self.tr("disconnected"))),
            SetRow::Language => {
                let key = match self.settings.language.as_str() {
                    "pt" => "lang_pt",
                    "es" => "lang_es",
                    _ => "lang_en",
                };
                (self.tr("language"), format!("‹{} ›", self.tr(key)))
            }
            SetRow::Theme => {
                // the name comes from the theme file (its id when it has none)
                let name = self.themes.name(&self.settings.theme, &self.settings.language);
                (self.tr("theme"), format!("‹{name} ›"))
            }
            SetRow::Display => (self.tr("display"), self.tr(if self.settings.battery_percent { "on" } else { "off" })),
            SetRow::Volume => (self.tr("volume"), pct("volume")),
            SetRow::Brightness => (self.tr("brightness"), pct("brightness")),
            SetRow::System => (self.tr("system"), String::new()),
            SetRow::Update => (self.tr("update_lists"), String::new()),
            SetRow::RetroArch => (self.tr("retroarch"), String::new()),
            SetRow::Power => (self.tr("power_off"), String::new()),
        }
    }

    /// The Settings, measured on the prototype at 640x480 (1 em = 16 px):
    /// - header band 2.656 em: "Settings" 1.4 em bold at (1.4 em, 0.5625 em); the battery
    ///   ending 1.4 em from the right at 0.669 em;
    /// - the list from (1 em, 2.756 em), 15.96 em wide: items 1.669 em tall every 1.769 em,
    ///   the text 1.05 em, 0.84 em in and 0.21 em down; the focused one a `sel_bg` pill;
    /// - the panel from 17.76 em to 1 em from the right edge, down to 0.4 em above the hints,
    ///   `radius_panel`, `panel_bg`, padding 0.6 em on top and 0.9 em on the sides: its title
    ///   1.2 em bold; then 2.34 em from its top, the item's content in 1.4875 em rows (text
    ///   1 em, 0.3 em in, 0.12 em down): the options with a pill and ✓ on the chosen one
    ///   (language, theme), label and value lines (Wi-Fi, Bluetooth, System, with 0.5625 em
    ///   bars), or the level 1.6 em bold over a bar (volume, brightness); the note 0.9 em,
    ///   muted, 0.4375 em under the content;
    /// - hints ▲▼ Navigate, then ◀▶ to adjust or A Open, and B Back.
    fn draw_settings(&mut self, c: &mut dyn Canvas, w: i32, h: i32) {
        let th = self.theme.clone();
        let rows = self.set_rows();
        let focus = self.settings_focus.min(rows.len() - 1);
        let em = w as f32 / 40.0;
        let e = |v: f32| (v * em).round() as i32;
        let ef = |v: f32| v * em;
        // header
        let title_px = ef(1.4);
        let batt_x = self.draw_status_battery(c, w);
        c.text_bold(&self.tr("settings"), e(1.4), e(0.5625), title_px, th.color("fg"), Align::Left, batt_x - e(2.4));
        // the list
        let top = ef(2.756);
        let bottom = (h - e(2.394) - e(0.4)) as f32;
        let (item_h, pitch) = (ef(1.669), ef(1.769));
        let list = Rect::new(e(1.0), top.round() as i32, e(15.96), (bottom - top).round() as i32);
        let visible = (((bottom - top) + (pitch - item_h)) / pitch).max(1.0) as usize;
        let first = focus.saturating_sub(visible - 1);
        let item_px = ef(1.05);
        for (i, row) in rows.iter().enumerate().skip(first).take(visible) {
            let y0 = top + (i - first) as f32 * pitch;
            let r = Rect::new(list.x, y0.round() as i32, list.w, (y0 + item_h).round() as i32 - y0.round() as i32);
            let sel = i == focus;
            if sel {
                c.fill(r, r.h / 2, th.color("sel_bg"));
            }
            let (label, _) = self.set_row_texts(*row);
            c.text(&label, r.x + e(0.84), r.y + e(0.21), item_px, th.color(if sel { "sel_fg" } else { "fg" }), Align::Left, r.w - e(1.68));
        }
        // the panel of the focused item
        let panel = Rect::new(e(17.76), top.round() as i32, w - e(1.0) - e(17.76), (bottom - top).round() as i32);
        c.fill(panel, th.em("radius_panel", w), th.color("panel_bg"));
        let inner = Rect::new(panel.x + e(0.9), panel.y + e(0.6), panel.w - 2 * e(0.9), panel.h - e(0.6));
        let row = rows[focus];
        let (label, _) = self.set_row_texts(row);
        c.text_bold(&label, inner.x, inner.y, ef(1.2), th.color("fg"), Align::Left, inner.w);
        let line_h = ef(1.4875);
        let px = ef(1.0);
        let mut y = panel.y as f32 + ef(2.34);
        // one line of the panel: a pill when chosen, the text, and a value or a ✓ on the right
        let line = |me: &mut Self, c: &mut dyn Canvas, y: f32, text: &str, value: Option<&str>, chosen: bool, muted_label: bool| {
            let r = Rect::new(inner.x, y.round() as i32, inner.w, (y + line_h).round() as i32 - y.round() as i32);
            if chosen {
                c.fill(r, r.h / 2, th.color("sel_bg"));
            }
            let fg = th.color(if chosen { "sel_fg" } else { "fg" });
            let label_fg = if muted_label && !chosen { th.color("muted") } else { fg };
            let ty = r.y + e(0.12);
            let vw = value.map_or(0, |v| c.text_width(v, px));
            c.text(text, r.x + e(0.3), ty, px, label_fg, Align::Left, r.w - e(0.6) - vw - e(0.5));
            if let Some(v) = value {
                c.text(v, r.right() - e(0.3), ty, px, fg, Align::Right, vw + 1);
            }
            if chosen && value.is_none() {
                // the ✓, drawn (the font has none), the text's size
                if let Some((t, _)) = me.symbol(c, "@check") {
                    let d = (px * 0.8).round() as i32;
                    c.draw_mask(t, Rect::new(r.right() - e(0.3) - d, r.y + (r.h - d) / 2, d, d), fg);
                }
            }
        };
        let mut note: Option<(&'static str, bool)> = None; // (text key, with the ◀▶ arrows)
        match row {
            SetRow::Language => {
                for l in LANGUAGES {
                    let name = self.tr(match *l {
                        "pt" => "lang_pt",
                        "es" => "lang_es",
                        _ => "lang_en",
                    });
                    line(self, c, y, &name, None, *l == self.settings.language, false);
                    y += line_h;
                }
                note = Some(("hint_adjust", true));
            }
            SetRow::Theme => {
                let current = self.themes.chosen(&self.settings.theme).to_string();
                for id in self.themes.list() {
                    let name = self.themes.name(&id, &self.settings.language);
                    line(self, c, y, &name, None, id == current, false);
                    y += line_h;
                }
                note = Some(("hint_adjust", true));
            }
            SetRow::Volume | SetRow::Brightness => {
                let key = if row == SetRow::Volume { "volume" } else { "brightness" };
                let level = self.level.get(key).copied();
                let big = level.map_or_else(|| "—".to_string(), |v| format!("{v}%"));
                c.text_bold(&big, inner.x, y.round() as i32, ef(1.6), th.color("fg"), Align::Left, inner.w);
                y += ef(1.76) + ef(0.175);
                if let Some(v) = level {
                    self.draw_level_bar(c, Rect::new(inner.x, y.round() as i32, inner.w, e(0.5625)), v as u32 * 100);
                }
                y += ef(0.5625);
                note = Some(("hint_adjust", true));
            }
            SetRow::Display => {
                // one option for now: a line with its value, as the label/value lines
                let value = self.tr(if self.settings.battery_percent { "on" } else { "off" });
                line(self, c, y, &self.tr("battery_percent"), Some(&value), false, false);
                y += line_h;
                note = Some(("hint_adjust", true));
            }
            SetRow::Wifi | SetRow::Bluetooth => {
                let (_, value) = self.set_row_texts(row);
                line(self, c, y, &self.tr("status"), Some(&value), false, true);
                y += line_h;
            }
            SetRow::System => {
                let info = self.info.as_ref().map(|(_, i)| i.clone()).unwrap_or_default();
                for (k, v) in &info {
                    let label = self.texts.get(k).to_string();
                    line(self, c, y, &label, Some(v), false, true);
                    y += line_h;
                    if *k == "memory" {
                        if let Some(share) = used_share(v) {
                            y += ef(0.175);
                            self.draw_level_bar(c, Rect::new(inner.x, y.round() as i32, inner.w, e(0.5625)), share);
                            y += ef(0.5625) + ef(0.35);
                        }
                    }
                }
            }
            SetRow::Update | SetRow::RetroArch | SetRow::Power => {
                note = Some(("note_open", false));
            }
        }
        if let Some((key, arrows)) = note {
            let npx = ef(0.9);
            let ny = (y + ef(0.4375)).round() as i32;
            let mut nx = inner.x;
            if arrows {
                // ◀ ▶ before the text (the font has no such glyphs)
                let (tw, tht) = ((npx * 0.62).round() as i32, (npx * 0.76).round() as i32);
                let cy = ny + (npx * 0.6).round() as i32;
                let muted = th.color("muted");
                triangle(c, nx + tw / 2, cy, tw, tht, Dir::Left, muted);
                nx += tw + e(0.25);
                triangle(c, nx + tw / 2, cy, tw, tht, Dir::Right, muted);
                nx += tw + e(0.35);
            }
            c.text(&self.tr(key), nx, ny, npx, th.color("muted"), Align::Left, inner.right() - nx);
        }
        let mut hints = vec![(NAV_UD, self.tr("hint_navigate"))];
        match row {
            SetRow::Language | SetRow::Theme | SetRow::Display | SetRow::Volume | SetRow::Brightness => hints.push((NAV_LR, self.tr("hint_adjust"))),
            SetRow::Update | SetRow::RetroArch | SetRow::Power => hints.push(("A", self.tr("hint_open"))),
            _ => {}
        }
        hints.push(("B", self.tr("hint_back")));
        self.draw_hints(c, w, h, &hints);
    }

    /// A horizontal level bar: the track (the muted color at 30%, as the prototype) and the
    /// accent part, `share` in 1/10000.
    fn draw_level_bar(&self, c: &mut dyn Canvas, r: Rect, share: u32) {
        let th = &self.theme;
        let mut track = th.color("muted");
        track.a = 77;
        c.fill(r, r.h / 2, track);
        let fw = (r.w as i64 * share.min(10000) as i64 / 10000) as i32;
        if fw > 0 {
            c.fill(Rect::new(r.x, r.y, fw.max(r.h), r.h), r.h / 2, th.color("accent"));
        }
    }
}

/// The used share (1/10000) of a "used / total ..." text of the System panel.
fn used_share(v: &str) -> Option<u32> {
    let (a, b) = v.split_once(" / ")?;
    let used: f64 = a.trim().parse().ok()?;
    let total: f64 = b.split_whitespace().next()?.parse().ok()?;
    (total > 0.0).then(|| (used / total * 10000.0).round() as u32)
}

/// Largest side of a decoded Dock icon (the focused tile is about 170 px at 640x480).
const ICON_PX: u32 = 192;

/// A PNG as a mask fitting `max` x `max`: its alpha, or its brightness when it is opaque
/// (a white logo on black). None if it is not a valid PNG or is too large to decode.
pub fn icon_mask(path: &std::path::Path, max: u32) -> Option<(u32, u32, Vec<u8>)> {
    let mut reader = image::ImageReader::open(path).ok()?.with_guessed_format().ok()?;
    let mut limits = image::Limits::default();
    limits.max_alloc = Some(32 << 20);
    reader.limits(limits);
    let img = reader.decode().ok()?.to_rgba8();
    let (iw, ih) = img.dimensions();
    let k = f64::min(max as f64 / iw.max(1) as f64, max as f64 / ih.max(1) as f64).min(1.0);
    let (w, h) = (((iw as f64 * k).round() as u32).max(1), ((ih as f64 * k).round() as u32).max(1));
    let small = image::imageops::resize(&img, w, h, image::imageops::FilterType::Triangle);
    let opaque = small.pixels().all(|p| p[3] == 255);
    let alpha = small
        .pixels()
        .map(|p| if opaque { ((p[0] as u32 * 3 + p[1] as u32 * 6 + p[2] as u32) / 10) as u8 } else { p[3] })
        .collect();
    Some((w, h, alpha))
}

/// The CSS timing function cubic-bezier(x1, y1, x2, y2) at progress `t` (0..1): the curve's
/// x is solved for `t` (Newton, then bisection), and its y returned. y may pass 1 (a spring).
pub fn cubic_bezier(x1: f32, y1: f32, x2: f32, y2: f32, t: f32) -> f32 {
    let t = t.clamp(0.0, 1.0);
    let bez = |a: f32, b: f32, s: f32| 3.0 * a * s * (1.0 - s).powi(2) + 3.0 * b * s * s * (1.0 - s) + s.powi(3);
    let dbez = |a: f32, b: f32, s: f32| 3.0 * a * (1.0 - s).powi(2) + 6.0 * (b - a) * s * (1.0 - s) + 3.0 * (1.0 - b) * s * s;
    let mut s = t;
    for _ in 0..8 {
        let d = dbez(x1, x2, s);
        if d.abs() < 1e-6 {
            break;
        }
        s = (s - (bez(x1, x2, s) - t) / d).clamp(0.0, 1.0);
    }
    if (bez(x1, x2, s) - t).abs() > 1e-4 {
        let (mut lo, mut hi) = (0.0f32, 1.0f32);
        for _ in 0..30 {
            s = (lo + hi) / 2.0;
            if bez(x1, x2, s) < t {
                lo = s;
            } else {
                hi = s;
            }
        }
    }
    bez(y1, y2, s)
}

/// A side of the screen for a level line (volume right; brightness left, P-62).
#[derive(Clone, Copy)]
#[allow(dead_code)]
enum Edge {
    Left,
    Right,
}

#[derive(Clone, Copy)]
enum Dir {
    Left,
    Right,
    Up,
    Down,
}

/// A filled triangle `w` x `h` centered on (cx, cy), pointing to `dir`, made of 1 px lines
/// (fills only: any backend, any font).
fn triangle(c: &mut dyn Canvas, cx: i32, cy: i32, w: i32, h: i32, dir: Dir, color: crate::canvas::Color) {
    let (w, h) = (w.max(2), h.max(2));
    match dir {
        Dir::Left | Dir::Right => {
            for i in 0..w {
                // column i from the tip: its height grows to h at the base
                let hh = h * (i + 1) / w;
                let x = if matches!(dir, Dir::Left) { cx - w / 2 + i } else { cx + w / 2 - 1 - i };
                c.fill(Rect::new(x, cy - hh / 2, 1, hh.max(1)), 0, color);
            }
        }
        Dir::Up | Dir::Down => {
            for i in 0..h {
                let ww = w * (i + 1) / h;
                let y = if matches!(dir, Dir::Up) { cy - h / 2 + i } else { cy + h / 2 - 1 - i };
                c.fill(Rect::new(cx - ww / 2, y, ww.max(1), 1), 0, color);
            }
        }
    }
}

/// The backspace icon centered on (cx, cy), `size` wide: a left arrow head made of 1 px
/// columns and a shaft, with fills only (works on any backend and font).
fn back_icon(c: &mut dyn Canvas, cx: i32, cy: i32, size: i32, color: crate::canvas::Color) {
    let size = size.max(8);
    let head = size * 2 / 5;
    let half = size * 2 / 5;
    let x0 = cx - size / 2;
    for i in 0..head {
        let hh = half * (i + 1) / head;
        c.fill(Rect::new(x0 + i, cy - hh, 1, 2 * hh + 1), 0, color);
    }
    let shaft = (size / 6).max(2);
    c.fill(Rect::new(x0 + head, cy - shaft / 2, size - head, shaft), 0, color);
}

/// Text keys built at run time: the System panel (the i18n test reads them). Theme names
/// come from each theme file.
pub const TEXT_KEYS: &[&str] = &["model", "cpu", "memory", "launcher_rss", "storage", "battery"];
