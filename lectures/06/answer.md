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

- 取り組んだレベル：基礎 / 実装 / 発展
- やったこと：
- 結果：
- 気づき・疑問：
