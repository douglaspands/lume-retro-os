# Spec Delta

## MODIFIED Requirements

### Requirement: Endereços fixos da rede USB
A rede USB MUST usar endereços fixos, conhecidos pelo PC sem descoberta, com uma sub-rede própria por console (GA36 em `10.55.0.0/24` com o console em `10.55.0.1`; R36S em `10.55.1.0/24` com o console em `10.55.1.1`), para os dois poderem estar ligados ao mesmo PC ao mesmo tempo, e MUST NOT oferecer rota para outras redes nem encaminhamento de pacotes.

#### Scenario: PC configura a rede sozinho
- **WHEN** o cabo é conectado a um PC Linux com NetworkManager
- **THEN** o PC recebe um endereço na rede USB e alcança o console pelo endereço fixo documentado

#### Scenario: Dois consoles no mesmo PC
- **WHEN** o GA36 e o R36S estão ligados ao mesmo PC pela porta OTG
- **THEN** o PC alcança o GA36 em `10.55.0.1` e o R36S em `10.55.1.1` ao mesmo tempo
