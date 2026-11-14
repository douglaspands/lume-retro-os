//! Cover textures with a fixed ceiling in bytes (spec game-launcher, "Memória com teto
//! fixo"): the least recently used ones are freed first, whatever the size of the collection.

use std::collections::HashMap;
use std::hash::Hash;

pub struct Lru<K, V> {
    cap: usize,
    used: usize,
    tick: u64,
    map: HashMap<K, (V, usize, u64)>,
}

impl<K: Eq + Hash + Clone, V> Lru<K, V> {
    pub fn new(cap_bytes: usize) -> Lru<K, V> {
        Lru { cap: cap_bytes, used: 0, tick: 0, map: HashMap::new() }
    }

    pub fn used(&self) -> usize {
        self.used
    }

    pub fn len(&self) -> usize {
        self.map.len()
    }

    pub fn is_empty(&self) -> bool {
        self.map.is_empty()
    }

    pub fn get(&mut self, k: &K) -> Option<&V> {
        self.tick += 1;
        let tick = self.tick;
        self.map.get_mut(k).map(|e| {
            e.2 = tick;
            &e.0
        })
    }

    /// Inserts and returns what had to go to stay under the ceiling (to free in the backend).
    /// An entry larger than the whole ceiling is refused and returned at once.
    pub fn insert(&mut self, k: K, v: V, bytes: usize) -> Vec<V> {
        let mut out = Vec::new();
        if bytes > self.cap {
            out.push(v);
            return out;
        }
        if let Some((old, size, _)) = self.map.remove(&k) {
            self.used -= size;
            out.push(old);
        }
        while self.used + bytes > self.cap {
            let oldest = self.map.iter().min_by_key(|(_, e)| e.2).map(|(k, _)| k.clone());
            let Some(o) = oldest else { break };
            let (v, size, _) = self.map.remove(&o).unwrap();
            self.used -= size;
            out.push(v);
        }
        self.tick += 1;
        self.used += bytes;
        self.map.insert(k, (v, bytes, self.tick));
        out
    }

    /// Everything, to free (theme or tile size changed).
    pub fn drain(&mut self) -> Vec<V> {
        self.used = 0;
        self.map.drain().map(|(_, (v, _, _))| v).collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn never_above_the_ceiling() {
        let mut l: Lru<u32, u32> = Lru::new(1000);
        let mut freed = 0;
        for i in 0..5000 {
            freed += l.insert(i, i, 96).len();
            assert!(l.used() <= 1000);
        }
        assert_eq!(l.len(), 10);
        assert_eq!(freed, 4990);
    }

    #[test]
    fn recently_used_stays() {
        let mut l: Lru<u32, &str> = Lru::new(300);
        l.insert(1, "a", 100);
        l.insert(2, "b", 100);
        l.insert(3, "c", 100);
        assert!(l.get(&1).is_some());
        assert_eq!(l.insert(4, "d", 100), vec!["b"]);
        assert!(l.get(&1).is_some() && l.get(&2).is_none());
        assert_eq!(l.insert(5, "huge", 301), vec!["huge"]);
    }
}
