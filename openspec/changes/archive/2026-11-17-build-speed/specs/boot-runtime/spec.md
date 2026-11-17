# Spec Delta

## ADDED Requirements

### Requirement: Serviços que o jogo não usa depois do frontend
O boot MUST iniciar os serviços em paralelo quando as dependências permitem, e MUST iniciar depois
do frontend os serviços que nenhum jogo usa (Bluetooth, NetworkManager, playlists do RetroArch,
índice do launcher); a rede USB MUST continuar subindo antes do frontend.

#### Scenario: Frontend antes do Bluetooth
- **WHEN** um console inicia
- **THEN** o log do boot mostra o frontend iniciado antes do Bluetooth e do NetworkManager, e o `boot OK completed` chega mais cedo que antes desta mudança no mesmo console

#### Scenario: Cabo USB logo no boot
- **WHEN** o console inicia com o cabo do PC na porta OTG
- **THEN** o PC alcança o console pela rede USB antes de o frontend iniciar
