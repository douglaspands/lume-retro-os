/* lume-launcher · adaptador de sistema (SIMULADO).
   É a fronteira com o aparelho. No app real, cada função aqui vira uma chamada ao dArkOS:
     wifi/bt      → detectar adaptador e chamar as ferramentas de rede do sistema, sob demanda
     metrics      → ler /proc e /sys, só enquanto o menu Sistema estiver aberto
   O motor de UI só conhece esta interface, então trocar o simulado pelo real não mexe nas telas. */
(function () {
  'use strict';
  const Lume = (window.Lume = window.Lume || {});

  const NETS = [{ n: 'Casa_5G', q: 3 }, { n: 'Vizinho_2G', q: 1 }, { n: 'Cafe_Livre', q: 2 }, { n: 'Escritorio', q: 2 }];
  const DEVS = [{ n: 'Controle BT Pro', ic: '🎮' }, { n: 'Fone sem fio', ic: '🎧' }, { n: 'Teclado mini', ic: '⌨' }];

  /* inicia a amostragem de CPU/memória; devolve o valor atual e uma função para parar */
  function startMetrics(onTick) {
    const s = { cpu: 12, freq: 1008, temp: 41, used: 310, rss: 14 };
    const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
    const timer = setInterval(() => {
      s.cpu = clamp(Math.round(s.cpu + (Math.random() - .5) * 8), 3, 60);
      s.freq = s.cpu > 30 ? 1296 : 1008;
      s.temp = clamp(Math.round(s.temp + (Math.random() - .5) * 2), 36, 58);
      s.used = clamp(Math.round(s.used + (Math.random() - .5) * 12), 250, 420);
      s.rss = clamp(Math.round(s.rss + (Math.random() - .5) * 1.5), 12, 18);
      onTick(s);
    }, 1000);
    return { value: s, stop: () => clearInterval(timer) };
  }

  Lume.system = { wifi: { networks: NETS }, bt: { devices: DEVS }, startMetrics };
})();
