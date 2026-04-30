# VILU — Sistema de Recomendação de Filmes com Feed Social

## Estrutura do projeto

```
TCC_VILU/
├── app.py               ← servidor Flask (rotas, TMDB, feed)
├── auth.py              ← login, cadastro, logout
├── database.py          ← banco SQLite (4 tabelas)
├── sistema_xai.py       ← algoritmos de recomendação + XAI
├── .gitignore           ← arquivos ignorados pelo Git
├── static/
│   └── style.css        ← visual dark mode + estilos do feed
├── templates/
│   ├── base.html        ← navbar + estrutura comum
│   ├── index.html       ← busca e recomendações
│   ├── detalhes.html    ← detalhes + avaliação + comentário
│   ├── feed.html        ← feed social com todos os posts
│   ├── perfil.html      ← histórico + publicações do usuário
│   ├── usuario_publico.html ← perfil público de outro usuário
│   ├── login.html       ← tela de login
│   ├── cadastro.html    ← criar conta
│   └── 404.html         ← página de erro
└── dataset/             ← baixar do MovieLens (não sobe no Git)
    ├── movies.csv
    └── ratings.csv
```

---

## Instalação e execução

### 1. Instalar dependências
```
pip install flask pandas requests werkzeug
```

### 2. Baixar o dataset
Acesse https://grouplens.org/datasets/movielens/latest
Baixe `ml-latest-small.zip`, extraia e coloque `movies.csv` e `ratings.csv` na pasta `dataset/`

### 3. Criar o banco
```
python database.py
```

### 4. Rodar o servidor
```
python app.py
```

Acesse: http://localhost:5000

---

## Como usar o Git em equipe

### Configuração inicial (uma vez por máquina)
```
git config --global user.name "Seu Nome"
git config --global user.email "seu@email.com"
```

### Clonar o projeto (colegas)
```
git clone https://github.com/seu-usuario/VILU.git
cd VILU
pip install flask pandas requests werkzeug
# baixar o dataset manualmente (não sobe no Git)
python database.py
python app.py
```

### Fluxo de trabalho em equipe
```
git checkout -b feature/minha-funcionalidade  ← cria branch
# faz as mudanças...
git add .
git commit -m "descreve o que foi feito"
git push origin feature/minha-funcionalidade
# abre Pull Request no GitHub para revisar e juntar
```

### Atualizar seu código com o que os colegas fizeram
```
git checkout main
git pull origin main
```

---

## Funcionalidades

- Busca de filmes com recomendações híbridas (Colaborativo + Conteúdo)
- XAI: explicação personalizada citando o histórico do usuário logado
- Login, cadastro e logout com senha criptografada
- Avaliação privada (1-5 estrelas) que alimenta as recomendações
- Feed social: comentários públicos com nota, visíveis para todos
- Curtidas nos comentários (toggle sem recarregar a página)
- Perfil público de cada usuário com suas publicações
- Excluir próprios comentários

---

## Tabelas do banco

| Tabela | Descrição |
|---|---|
| users | Cadastros de usuários |
| avaliacoes | Notas privadas (1 por usuário/filme) — usadas pelo XAI |
| comentarios | Posts públicos do feed (múltiplos por usuário/filme) |
| curtidas | Registro de curtidas nos comentários |
