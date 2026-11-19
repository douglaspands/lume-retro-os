# Spec Delta

## ADDED Requirements

### Requirement: Cópia de arquivos pela rede USB
No papel device, o servidor SSH da rede USB MUST aceitar cópia de arquivos por `scp`, por `sftp`
e por `rsync`, nos dois sentidos, com as mesmas regras de acesso do SSH. Nenhum serviço novo MUST
rodar no boot por causa disso: os programas de cópia só rodam quando uma sessão os chama.

#### Scenario: scp padrão do PC
- **WHEN** o PC roda `scp jogo.zip root@<endereço do console>:/storage/roms/nes/` sem opções extras
- **THEN** o arquivo chega ao cartão com o mesmo SHA256

#### Scenario: Gerenciador de arquivos do PC
- **WHEN** o usuário abre `sftp://root@<endereço do console>/storage` no gerenciador de arquivos do PC
- **THEN** a `ROMS` aparece para leitura e escrita

#### Scenario: Cópia interrompida
- **WHEN** uma cópia por `rsync` de um jogo de CD é cortada no meio e repetida
- **THEN** a segunda cópia continua de onde parou e termina com o mesmo SHA256 do PC

#### Scenario: Boot sem custo novo
- **WHEN** o console liga sem o cabo do PC
- **THEN** nenhum processo de `sftp` ou de `rsync` está rodando
