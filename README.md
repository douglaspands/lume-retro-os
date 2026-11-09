# Lume Retro OS

Distro Alpine Linux com RetroArch para o R36S (RK3326), o clone GA36-MB V1.2 (A33) e uma VM x86_64 de teste.

`r36os` é o nome interno do orquestrador, dos pacotes e dos serviços.

```
uv run r36os build vm      # gera out/vm/vm.img
uv run r36os vm            # roda a VM em janela (--headless para serial no terminal)
uv run r36os test-vm       # teste de aceitação
```

Planejamento: `openspec/changes/alpine-retroarch-distro/`.
