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
    Lite,
    Volume,
    Brightness,
    System,
    Update,
    RetroArch,
    Power,
}

enum Overlay {
    /// game menu (Some(game)) or console options (None) of a system
    Menu { sys: usize, game: Option<GameRef>, focus: usize },
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

const KEYS: &[&str] = &["abcdefghij", "klmnopqrst", "uvwxyz0123", "456789-'.&"];
/// keys of the last keyboard row, after the characters
const KEY_ACTIONS: usize = 3; // space, clear, done

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
const FRAME: Duration = Duration::from_millis(33);

impl<S: SystemAdapter> App<S> {
    pub fn new(p: Paths, catalog: Catalog, runners: BTreeMap<String, Runner>, arch: &str, sys: S) -> App<S> {
        let card = p.storage.join("system/lume");
        let settings_path = card.join("settings.toml");
        let settings = Settings::load(&settings_path);
        let themes = Themes::new(&card, &p.share);
        let mut theme = themes.load_or_default(&settings.theme);
        if settings.lite {
            theme = theme.lite();
        }
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
            dock: Vec::new(),
            dock_focus: 0,
            grid: None,
            settings_focus: 0,
            info: None,
            level: BTreeMap::new(),
            thumbs: Lru::new(cache),
            free_list: Vec::new(),
            icons: BTreeMap::new(),
            jump: Jump { last: None, speed: 1 },
            exit: None,
            updating: None,
            start_update: false,
            anim: None,
            cols: 4,
            rows: 2,
        };
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
            "settings" => self.screen = Screen::Settings,
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
            ListKind::Recent => self.lib.recents(50),
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
                self.overlay = Some(Overlay::Keyboard { focus: 0 });
                return;
            }
            Action::Y => {
                if let ListKind::System(s) = g.kind {
                    self.overlay = Some(Overlay::Menu { sys: s, game: None, focus: 0 });
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
                self.overlay = Some(Overlay::Menu { sys: game.sys, game: Some(game), focus: 0 });
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

    fn menu_rows(&self, sys: usize, game: Option<GameRef>) -> Vec<Row> {
        let eff = self.effective(sys, game);
        let libretro = self.runner_of(&eff.emulator).is_some_and(|r| r.kind == Kind::Libretro);
        let mut rows = Vec::new();
        if game.is_some() {
            rows.extend([Row::Start, Row::StartState]);
        }
        rows.push(Row::Emulator);
        if libretro {
            rows.extend([Row::Aspect, Row::Shader]);
        }
        rows.push(if game.is_some() { Row::Favorite } else { Row::ClearGames });
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
            Overlay::Menu { sys, game, mut focus } => {
                let rows = self.menu_rows(sys, game);
                focus = focus.min(rows.len() - 1);
                match a {
                    Action::B => return None,
                    Action::Up => focus = focus.saturating_sub(1),
                    Action::Down => focus = (focus + 1).min(rows.len() - 1),
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
                Some(Overlay::Menu { sys, game, focus })
            }
            Overlay::Slots { game, slots, mut focus } => {
                match a {
                    Action::B => return Some(Overlay::Menu { sys: game.sys, game: Some(game), focus: 1 }),
                    Action::Up => focus = focus.saturating_sub(1),
                    Action::Down => focus = (focus + 1).min(slots.len() - 1),
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
                match a {
                    Action::Left => c = (c + row_len(r) - 1) % row_len(r),
                    Action::Right => c = (c + 1) % row_len(r),
                    Action::Up => r = (r + KEYS.len()) % (KEYS.len() + 1),
                    Action::Down => r = (r + 1) % (KEYS.len() + 1),
                    Action::B => {
                        let g = self.grid.as_mut()?;
                        // B on an empty filter closes the keyboard
                        g.filter.pop()?;
                        self.apply_filter();
                    }
                    Action::Start => return None,
                    Action::A => {
                        let g = self.grid.as_mut()?;
                        if r < KEYS.len() {
                            g.filter.push(KEYS[r].chars().nth(c).unwrap());
                        } else {
                            match c {
                                0 => g.filter.push(' '),
                                1 => g.filter.clear(),
                                _ => return None,
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
        v.extend([SetRow::Language, SetRow::Theme, SetRow::Lite, SetRow::Volume, SetRow::Brightness, SetRow::System, SetRow::Update, SetRow::RetroArch, SetRow::Power]);
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
        let mut t = self.themes.load_or_default(&self.settings.theme);
        if self.settings.lite {
            t = t.lite();
        }
        self.theme = t;
        for (_, icon) in std::mem::take(&mut self.icons) {
            if let Some((t, _)) = icon {
                self.free_list.push(t);
            }
        }
    }

    /// The Dock icon of a system from the theme folder, decoded once (only a card theme
    /// brings icons; the distro has none).
    fn icon(&mut self, c: &mut dyn Canvas, id: &str) -> Option<(TextureId, Rect)> {
        if let Some(i) = self.icons.get(id) {
            return *i;
        }
        let tile = lume_index::thumbs::Tile { w: 128, h: 128 };
        let made = self.theme.dir.as_ref().map(|d| d.join("icons").join(format!("{id}.png"))).filter(|p| p.exists()).and_then(|p| {
            let px = lume_index::thumbs::render(&p, tile)?;
            let (cw, ch) = (u16::from_le_bytes([px[0], px[1]]) as i32, u16::from_le_bytes([px[2], px[3]]) as i32);
            let t = c.texture_rgb565(128, 128, &px[4..])?;
            Some((t, Rect::new((128 - cw) / 2, (128 - ch) / 2, cw.max(1), ch.max(1))))
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
            Action::Up => self.settings_focus = self.settings_focus.saturating_sub(1),
            Action::Down => self.settings_focus = (self.settings_focus + 1).min(rows.len() - 1),
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
                        let i = list.iter().position(|t| *t == self.settings.theme).unwrap_or(0) as i32;
                        self.settings.theme = list[(i + dir).rem_euclid(list.len() as i32) as usize].clone();
                        self.apply_theme();
                        self.save_settings();
                    }
                }
                SetRow::Lite => {
                    self.settings.lite = !self.settings.lite;
                    self.apply_theme();
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
                SetRow::Lite => {
                    self.settings.lite = !self.settings.lite;
                    self.apply_theme();
                    self.save_settings();
                }
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
        match self.screen {
            Screen::Dock => self.draw_dock(c, w, h),
            Screen::Grid => self.draw_grid(c, w, h),
            Screen::Settings => self.draw_settings(c, w, h),
        }
        if let Some(ov) = &self.overlay {
            let ov = match ov {
                Overlay::Menu { sys, game, focus } => Overlay::Menu { sys: *sys, game: *game, focus: *focus },
                Overlay::Slots { game, slots, focus } => Overlay::Slots { game: *game, slots: slots.clone(), focus: *focus },
                Overlay::Keyboard { focus } => Overlay::Keyboard { focus: *focus },
                Overlay::Confirm { focus } => Overlay::Confirm { focus: *focus },
            };
            self.draw_overlay(c, &ov, w, h);
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
        c.present();
    }

    fn label(&self, item: DockItem) -> (String, String) {
        match item {
            DockItem::Favorites => (self.tr("favorites"), self.tr("dock_favorites")),
            DockItem::Recent => (self.tr("recent"), self.tr("dock_recent")),
            DockItem::Settings => (self.tr("settings"), self.tr("dock_settings")),
            DockItem::System(s) => (self.lib.systems[s].name.clone(), self.lib.systems[s].abbr.clone()),
        }
    }

    fn draw_dock(&mut self, c: &mut dyn Canvas, w: i32, h: i32) {
        let th = &self.theme.clone();
        let n = self.dock.len() as i32;
        let base = th.em("icon", w) as f32;
        let gap = base * th.num("dock_gap") as f32;
        let cy = (h as f64 * th.num("dock_top")) as i32;
        let (peak, low, spread) = (th.num("mag_peak") as f32, th.num("mag_base") as f32, th.num("mag_spread") as f32);
        let shift = match self.anim {
            Some((t, from)) => {
                let k = (t.elapsed().as_millis() as f32 / th.num("anim_ms").max(1.0) as f32).min(1.0);
                from * (1.0 - k) * (1.0 - k)
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
        let label_px = th.em("label_px", w) as f32;
        for (x, size, idx) in placed {
            let r = Rect::new(w / 2 + x as i32 - size as i32 / 2, cy - size as i32 / 2, size as i32, size as i32);
            if r.right() < 0 || r.x > w {
                continue;
            }
            let focused = idx == self.dock_focus;
            let (bg, fg) = if focused { (th.color("icon_sel_bg"), th.color("icon_sel_fg")) } else { (th.color("icon_bg"), th.color("icon_fg")) };
            c.fill(r, th.em("radius_icon", w) * size as i32 / base as i32, bg);
            let icon = match self.dock[idx] {
                DockItem::System(s) => {
                    let id = self.lib.systems[s].id.clone();
                    self.icon(c, &id)
                }
                _ => None,
            };
            match icon {
                Some((t, src)) => c.draw_texture(t, src, r.inset(r.w / 8)),
                None => {
                    let (_, abbr) = self.label(self.dock[idx]);
                    let px = (size * 0.30).max(10.0);
                    c.text(&abbr, r.x + r.w / 2, r.y + (r.h - px as i32) / 2, px, fg, Align::Center, r.w - 8);
                }
            }
        }
        let (name, _) = self.label(self.dock[self.dock_focus]);
        let title_px = th.em("title_px", w) as f32;
        let ty = cy + (base * peak) as i32 / 2 + title_px as i32 / 2;
        c.text(&name, w / 2, ty, title_px, th.color("fg"), Align::Center, w - 32);
        if let DockItem::System(s) = self.dock[self.dock_focus] {
            let count = format!("{} {}", self.lib.systems[s].index.len(), self.tr("games"));
            c.text(&count, w / 2, ty + title_px as i32 + 6, label_px * 0.85, th.color("muted"), Align::Center, w - 32);
        }
        self.draw_hints(c, w, h, &[("A", self.tr("hint_select"))]);
    }

    fn draw_hints(&self, c: &mut dyn Canvas, w: i32, h: i32, hints: &[(&str, String)]) {
        let th = &self.theme;
        let px = th.em("label_px", w) as f32 * 0.8;
        let y = h - px as i32 - 10;
        let mut x = w - 16;
        for (btn, text) in hints.iter().rev() {
            let tw = c.text_width(text, px);
            x -= tw;
            c.text(text, x, y, px, th.color("muted"), Align::Left, tw + 1);
            if btn.is_empty() {
                x -= 18;
                continue;
            }
            let bw = px as i32 + 8;
            x -= bw + 6;
            c.fill(Rect::new(x, y - 2, bw, px as i32 + 4), (px as i32 + 4) / 2, th.color("accent"));
            c.text(btn, x + bw / 2, y, px * 0.85, th.color("accent_fg"), Align::Center, bw);
            x -= 18;
        }
    }

    fn list_title(&self, k: ListKind) -> String {
        match k {
            ListKind::Favorites => self.tr("favorites"),
            ListKind::Recent => self.tr("recent"),
            ListKind::System(s) => self.lib.systems[s].name.clone(),
        }
    }

    fn draw_grid(&mut self, c: &mut dyn Canvas, w: i32, h: i32) {
        let th = self.theme.clone();
        let Some(kind) = self.grid.as_ref().map(|g| g.kind) else { return };
        let title_px = th.em("title_px", w) as f32;
        let label_px = th.em("label_px", w) as f32 * 0.85;
        let margin = w / 40;
        let top = title_px as i32 + margin * 2;
        let footer = (label_px * 2.2) as i32;
        let cols = th.num("cols").max(1.0) as i32;
        let gap = margin;
        let tile_w = (w - 2 * margin - (cols - 1) * gap) / cols;
        let art_h = tile_w * 3 / 4;
        let tile_h = art_h + (label_px * 1.6) as i32;
        let avail = h - top - footer;
        // a square screen gets more rows (spec: layout independent of the resolution)
        let rows = (th.num("rows") as i32).max(avail / (tile_h + gap)).max(1);
        self.cols = cols as usize;
        self.rows = rows as usize;
        self.scroll_to_focus();
        let title = self.list_title(kind);
        let g = self.grid.as_ref().unwrap();
        let (filter, items, focus, gtop) = (g.filter.clone(), g.items.clone(), g.focus, g.top);
        let header = if filter.is_empty() { title } else { format!("{title} · “{filter}”") };
        c.text(&header, margin, margin, title_px, th.color("fg"), Align::Left, w - 2 * margin - 80);
        if !items.is_empty() {
            c.text(&format!("{}/{}", focus + 1, items.len()), w - margin, margin + 4, label_px, th.color("muted"), Align::Right, 120);
        }
        if items.is_empty() {
            let key = if !filter.is_empty() {
                "no_results"
            } else if kind == ListKind::Favorites {
                "no_favorites"
            } else {
                "no_recent"
            };
            c.text(&self.tr(key), w / 2, h / 2 - label_px as i32, label_px, th.color("muted"), Align::Center, w - 2 * margin);
        }
        let first = gtop * cols as usize;
        for (k, r) in items.iter().enumerate().skip(first).take((cols * rows) as usize) {
            let pos = (k - first) as i32;
            let x = margin + (pos % cols) * (tile_w + gap);
            let y = top + (pos / cols) * (tile_h + gap);
            let focused = k == focus;
            let tile = Rect::new(x, y, tile_w, tile_h);
            c.fill(tile, th.em("radius_tile", w), th.color(if focused { "tile_bg_sel" } else { "tile_bg" }));
            if focused {
                c.fill(Rect::new(x, y + tile_h - 4, tile_w, 4), 2, th.color("accent"));
            }
            let art = Rect::new(x + 6, y + 6, tile_w - 12, art_h - 6);
            let name = self.lib.name(*r).to_string();
            match self.texture(c, *r) {
                Some((t, src)) => {
                    // the image keeps its shape, centered in the art area
                    let k = f64::min(art.w as f64 / src.w as f64, art.h as f64 / src.h as f64);
                    let (dw, dh) = ((src.w as f64 * k) as i32, (src.h as f64 * k) as i32);
                    c.draw_texture(t, src, Rect::new(art.x + (art.w - dw) / 2, art.y + (art.h - dh) / 2, dw, dh));
                }
                None => {
                    // the generated box: the name on the tile color
                    c.fill(art, th.em("radius_tile", w) / 2, th.color("icon_bg"));
                    c.text(&name, art.x + art.w / 2, art.y + art.h / 2 - label_px as i32 / 2, label_px, th.color("icon_fg"), Align::Center, art.w - 8);
                }
            }
            c.text(&name, x + tile_w / 2, y + art_h + 4, label_px, th.color(if focused { "fg" } else { "muted" }), Align::Center, tile_w - 8);
            if self.has_badge(*r) {
                c.fill(Rect::new(x + tile_w - 16, y + 8, 10, 10), 5, th.color("accent"));
            }
            if self.lib.is_favorite(*r) && kind != ListKind::Favorites {
                // favorite: a dot in the text color, top left (the options badge is top right)
                c.fill(Rect::new(x + 6, y + 8, 10, 10), 5, th.color("fg"));
            }
        }
        let mut hints = vec![("A", self.tr("hint_select")), ("B", self.tr("hint_back")), ("X", self.tr("hint_search"))];
        if matches!(kind, ListKind::System(_)) {
            hints.push(("Y", self.tr("hint_options")));
        }
        self.draw_hints(c, w, h, &hints);
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
            Overlay::Menu { sys, game, focus } => {
                let rows = self.menu_rows(*sys, *game);
                let mut out = Vec::new();
                for row in &rows {
                    out.push(match row {
                        Row::Start => (self.tr("start"), String::new(), true),
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
                    Some(g) => self.lib.name(*g).to_string(),
                    None => format!("{} · {}", self.lib.systems[*sys].name, self.tr("console_options")),
                };
                self.draw_panel(c, w, h, &out, *focus, &title);
            }
            Overlay::Slots { game, slots, focus } => {
                let rows: Vec<(String, String, bool)> = slots
                    .iter()
                    .map(|s| (if s == "auto" { self.tr("slot_auto") } else { self.texts.n("slot", s) }, String::new(), true))
                    .collect();
                let title = format!("{} · {}", self.lib.name(*game), self.tr("start_state"));
                self.draw_panel(c, w, h, &rows, *focus, &title);
            }
            Overlay::Keyboard { focus } => {
                let th = self.theme.clone();
                let px = th.em("label_px", w) as f32;
                let key = (w - 64) / 10;
                let kh = (px * 1.8) as i32;
                let kb_h = kh * (KEYS.len() as i32 + 1) + 24;
                // above the button hints (label_px * 0.8 tall, 10 px from the bottom)
                let hints_h = (px * 0.8) as i32 + 20;
                let r = Rect::new(16, h - kb_h - hints_h, w - 32, kb_h);
                c.fill(r, th.em("radius_panel", w), th.color("panel_bg"));
                let (fr, fc) = (focus / 16, focus % 16);
                for (ri, row) in KEYS.iter().enumerate() {
                    for (ci, ch) in row.chars().enumerate() {
                        let k = Rect::new(r.x + 16 + ci as i32 * key, r.y + 12 + ri as i32 * kh, key - 4, kh - 4);
                        let sel = ri == fr && ci == fc;
                        c.fill(k, 8, th.color(if sel { "sel_bg" } else { "tile_bg" }));
                        c.text(&ch.to_string(), k.x + k.w / 2, k.y + (k.h - px as i32) / 2, px, th.color(if sel { "sel_fg" } else { "fg" }), Align::Center, k.w);
                    }
                }
                let labels = [self.tr("key_space"), self.tr("key_clear"), self.tr("key_done")];
                let aw = (r.w - 32) / 3;
                for (ci, l) in labels.iter().enumerate() {
                    let k = Rect::new(r.x + 16 + ci as i32 * aw, r.y + 12 + KEYS.len() as i32 * kh, aw - 4, kh - 4);
                    let sel = fr == KEYS.len() && fc == ci;
                    c.fill(k, 8, th.color(if sel { "sel_bg" } else { "tile_bg" }));
                    c.text(l, k.x + k.w / 2, k.y + (k.h - px as i32) / 2, px * 0.9, th.color(if sel { "sel_fg" } else { "fg" }), Align::Center, k.w - 8);
                }
            }
            Overlay::Confirm { focus } => {
                let rows = vec![(self.tr("cancel"), String::new(), true), (self.tr("power_off"), String::new(), true)];
                let title = self.tr("power_ask");
                self.draw_panel(c, w, h, &rows, *focus, &title);
            }
        }
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
                // the image themes have a translated name; a card theme shows its id
                let key = format!("theme_{}", self.settings.theme);
                let name = if TEXT_KEYS.contains(&key.as_str()) { self.texts.get(&key).to_string() } else { self.settings.theme.clone() };
                (self.tr("theme"), format!("‹{name} ›"))
            }
            SetRow::Lite => (self.tr("lite"), self.tr(if self.settings.lite { "on" } else { "off" })),
            SetRow::Volume => (self.tr("volume"), pct("volume")),
            SetRow::Brightness => (self.tr("brightness"), pct("brightness")),
            SetRow::System => (self.tr("system"), String::new()),
            SetRow::Update => (self.tr("update_lists"), String::new()),
            SetRow::RetroArch => (self.tr("retroarch"), String::new()),
            SetRow::Power => (self.tr("power_off"), String::new()),
        }
    }

    fn draw_settings(&mut self, c: &mut dyn Canvas, w: i32, h: i32) {
        let th = self.theme.clone();
        let rows = self.set_rows();
        let focus = self.settings_focus.min(rows.len() - 1);
        let title_px = th.em("title_px", w) as f32;
        let px = th.em("label_px", w) as f32;
        let margin = w / 40;
        c.text(&self.tr("settings"), margin, margin, title_px, th.color("fg"), Align::Left, w - 2 * margin);
        let row_h = (px * 1.75) as i32;
        let top = title_px as i32 + margin * 2;
        let info_open = rows.get(focus) == Some(&SetRow::System);
        let list_w = if info_open { w * 11 / 20 } else { w - 2 * margin };
        let visible = ((h - top - (px * 2.2) as i32) / row_h).max(1) as usize;
        let first = focus.saturating_sub(visible - 1);
        for (i, row) in rows.iter().enumerate().skip(first).take(visible) {
            let y = top + (i - first) as i32 * row_h;
            let r = Rect::new(margin, y, list_w, row_h - 4);
            let sel = i == focus;
            if sel {
                c.fill(r, th.em("radius_item", w).min(r.h / 2), th.color("sel_bg"));
            }
            let fg = th.color(if sel { "sel_fg" } else { "fg" });
            let (label, value) = self.set_row_texts(*row);
            let ty = r.y + (r.h - px as i32) / 2;
            let vw = if value.is_empty() || info_open { 0 } else { c.text_width(&value, px * 0.9) };
            c.text(&label, r.x + 14, ty, px, fg, Align::Left, r.w - 28 - vw - 12);
            if !value.is_empty() && !info_open {
                c.text(&value, r.right() - 14, ty, px * 0.9, if sel { fg } else { th.color("muted") }, Align::Right, r.w / 2);
            }
        }
        if info_open {
            let r = Rect::new(margin + list_w + margin, top, w - list_w - 3 * margin, h - top - (px * 2.2) as i32);
            c.fill(r, th.em("radius_panel", w), th.color("panel_bg"));
            let ipx = px * 0.75;
            let mut y = r.y + 12;
            if let Some((_, info)) = &self.info {
                for (k, v) in info {
                    c.text(self.texts.get(k), r.x + 12, y, ipx * 0.9, th.color("muted"), Align::Left, r.w - 24);
                    c.text(v, r.x + 12, y + ipx as i32, ipx, th.color("fg"), Align::Left, r.w - 24);
                    y += (ipx * 2.3) as i32;
                }
            }
        }
        let mut hints = vec![("A", self.tr("hint_select")), ("B", self.tr("hint_back"))];
        if matches!(rows.get(focus), Some(SetRow::Language | SetRow::Theme | SetRow::Volume | SetRow::Brightness)) {
            hints.insert(0, ("", self.tr("hint_adjust")));
        }
        self.draw_hints(c, w, h, &hints);
    }
}

/// Text keys built at run time: theme names and the System panel (the i18n test reads them)
pub const TEXT_KEYS: &[&str] = &["theme_material-dark", "theme_material-light", "model", "cpu", "memory", "launcher_rss", "storage", "battery"];
