# 第6回 解答

## 演習

<!-- [tool call] の行は、表示された行をそのまま貼り付けてください。終わらなかった STEP は、空欄のままでかまいません。 -->

- STEP 1 のツールの名前：`glossary_search_glossary`
- STEP 2 の [tool call]：`glossary_search_glossary({'query': '3レベル'})`
- STEP 3 の [tool call]：`fetch_fetch({'url': 'https://modelcontextprotocol.io/'})`, `glossary_search_glossary({'query': 'MCP'})`
- STEP 4 の [tool call]：`aws_aws___search_documentation({'search_phrase': 'Amazon S3 バージョニング 概要'})`, `aws_aws___search_documentation({'topics': ['general'], 'search_phrase': 'Amazon S3 versioning overview docs.aws.amazon.com'})`
- 気づき・疑問：STEP4において、tool callの２回目にsearch_phraseを英訳してコールしていた。tool returnの一部を見る限り、日本語での検索では十分な回答を得られていない可能異性がある。

## 宿題

<!-- 基礎・実装・発展のどれか1つに取り組めば完了です。 -->

- 取り組んだレベル：発展
- やったこと：自分が使っている「Open WebUI」におけるMCPサーバーの設定方法
- 結果：
  - 設定を書く場所
    - 外部で動くサーバー
      - WebコンソールのGUIでMCPサーバーのURLを指定可能
    - ローカルでstdioでやり取りするサーバー
      - Open WebUIが提供している`mcpo`というアプリで、stdioの入出力をHTTP経由のMCPに変換できるので、そのHTTPのURLをGUIで指定すれば使用可能
- 気づき・疑問：あえてstdioとOpen WebUIを直接接続でなく`mcpo`を使う理由は、Open WebUIから見た接続先がHTTPに統一できるからではないかと考える。また、WebアプリケーションであるOpen WebUIの扱いやすさから考えてもHTTP統一のメリットはあると考えられる。
