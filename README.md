# gns3lab

GNS3の構築を自動化するCLIツール。containerlabのように、トポロジをYAMLで定義して `deploy` / `destroy` するだけで使えます。

## セットアップ

```
pip install -e .
```

`gns3lab_config.yml.example` をコピーして `gns3lab_config.yml` を作成し、GNS3サーバーの接続情報を入力してください（このファイルはgit管理外です）。

```yaml
server:
  base: http://<GNS3サーバー>:3080/v2
  user: <ユーザー名>
  password: <パスワード>
```

## 別の環境（他の人のPC）へ移植するとき

このツールはリポジトリのコードだけでなく、**接続先のGNS3サーバー側の状態**にも依存します。
移植先ごとに必ず合わせる必要があるのは次の2点です。

### 1. アクセス先とアカウント（`gns3lab_config.yml`）

- `gns3lab_config.yml` は `.gitignore` 対象なので、`git clone` しただけでは付いてきません。
  フォルダごとコピーして渡す場合は、実際のパスワードが平文で入っているため、渡す前に
  `gns3lab_config.yml` を削除して `gns3lab_config.yml.example` だけ残してください。
- 移植先では `gns3lab_config.yml.example` をコピーして `gns3lab_config.yml` を作り、その環境に
  合わせて書き換えます。

  | 項目 | 確認方法 |
  |---|---|
  | `base`（GNS3サーバーのURL） | GNS3 GUIの `Edit > Preferences > Server > Local Server` にある Host/Port。同じPC上でGNS3を動かす場合は `http://127.0.0.1:<port>/v2` |
  | `user` / `password` | 同じ画面の Authentication欄。または `%APPDATA%\GNS3\<version>\gns3_server.ini`（GNS3 2.xの場合）の `[Server]` セクションにある `user` / `password`（`auth = True` の場合のみ必要。`auth = False` なら認証自体不要で `user`/`password` は空でも動きます） |

- 実行時にこのファイルが無いと `設定ファイルが見つかりません` というエラーで即終了するので、
  移植直後に何か動かない場合はまずここを確認してください。

### 2. テンプレート（`template:` に書く名前）

`topology.yml` の `template:` は文字列一致で **GNS3サーバー側に既に登録されているテンプレート名**
を参照します。このツール自体はテンプレートを作成しないため、移植先のGNS3サーバーに同名の
テンプレートが無ければ `deploy` はテンプレート未検出のエラーで失敗します。

- 移植先でまず次を実行し、実際に使えるテンプレート名を確認します。

  ```
  gns3lab templates
  ```

- `c3725` などのDynamips系ルータテンプレートは、**移植先のGNS3に同じIOSイメージが登録されて
  初めて使えます**。GNS3自体はCisco IOSイメージを配布していない（ライセンスの都合）ため、
  IOSイメージは利用者側で用意し、GNS3 GUIの `Edit > Preferences > Dynamips > IOS Routers`
  （または `File > Import appliance` でのアプライアンス取り込み）からテンプレートとして
  登録しておく必要があります。`VPCS` はGNS3に標準搭載されているため追加作業は不要です。
- 移植先で用意したテンプレート名が付属サンプルと異なる場合（例: `c3725` ではなく `c7200` を
  使っている等）は、`topology.yml` 側の `template:` を `gns3lab templates` の出力に合わせて
  書き換えてください。

## 使い方

### 1. 使えるテンプレート名を確認する

```
gns3lab templates
```

`name` 列の値をトポロジ定義の `template:` に使います。

### 2. トポロジをYAMLで定義する

`topology.yml` を参考に、好きな構成のファイルを作成します。

```yaml
name: mixed_lab

nodes:
  R1:
    template: Cisco_L3SW
    x: 0
    y: -200
  SW1:
    template: Cisco_L2SW
    x: 0
    y: 0
  PC1:
    template: VPCS
    x: -150
    y: 200

links:
  - [R1:0/0, SW1:0/0]
  - [SW1:0/1, PC1:0/0]
```

- `nodes`: ノード名 → テンプレート名・座標
- `links`: `[ノード名:adapter/port, ノード名:adapter/port]` の形式で2端点を指定

より複雑な構成例（MPLS L3VPN検証ラボ）は `mpls_topology.yml` を参照してください。

その他の構成例:

- `financial_wan_topology.yml`: 東京DC(本番)/大阪DC(DR)/本店をWAN経由で接続し、ASAvファイアウォールでDMZを分離した金融系トポロジー
- `wan_gre_mpls_redundancy.yml`: MPLSプライマリ経路 + GRE over IPsec VPNバックアップ経路によるWAN冗長化トポロジー
  - 設計書: [基本設計書](docs/wan-redundancy-basic-design.md) / [詳細設計書](docs/wan-redundancy-detailed-design.md)

### 2b. ノードに初期設定を持たせる（config自動投入）

各ノードに `config:` を書いておくと、`deploy` でノードを起動した直後にコンソール（telnet）
経由でCLIを自動投入します。GNS3のREST APIには設定注入用の専用エンドポイントが無いため、
実機のコンソールに接続してコマンドを打鍵する方式で代用しています。

```yaml
nodes:
  R1:
    template: c3725
    x: 0
    y: 0
    config: |
      hostname R1
      interface FastEthernet0/0
       ip address 10.0.0.1 255.255.255.0
       no shutdown

  PC1:
    template: VPCS
    x: 0
    y: 200
    config: |
      ip 10.0.0.10 255.255.255.0 10.0.0.1
      save
```

- 対応ノード種別: dynamips/IOU系ルータ（`enable` → `configure terminal` → 設定投入 →
  `end` → `write memory`）、VPCS（プロンプト待ちで行ごとに投入）。それ以外の種別は
  自動投入できないため警告を出してスキップします。
- enableパスワードが設定されているテンプレートの場合は `enable_password:` をノードに
  追加してください。
- 投入結果はノードごとに `ノード名: OK` / `ノード名: 失敗 - 理由` の形式で表示され、
  1ノードの失敗が他ノードの投入を止めることはありません。
- タイミング依存の自動操作のため、初回はGNS3のWebUIでコンソールを開いて実際に
  投入されたか目視確認することをおすすめします（dynamips系ノードは起動〜プロンプト
  表示までに数十秒かかることがあり、最大180秒待った上でタイムアウトします）。

### 3. デプロイ

```
gns3lab deploy topology.yml
```

プロジェクト作成 → ノード作成 → リンク作成 → 全ノード起動 → (config定義があれば)設定投入、
まで一括で行います。

- `--no-start`: ノードを起動しない（起動しないため設定投入も自動でスキップされます）
- `--no-config`: ノードは起動するが、`config:` の自動投入は行わない

```
gns3lab deploy topology.yml --no-config
```

同名プロジェクトが既に存在する場合はエラーになります（先に `destroy` してください）。

### 3b. 起動中のプロジェクトへ設定だけ再投入する

`topology.yml` の `config:` を書き換えた後、プロジェクトを作り直さずに設定だけ
再投入したい場合は `configure` を使います。

```
gns3lab configure topology.yml
```

- `topology.yml` の `name` からプロジェクトを検索し、既存ノードの一覧を取得した上で、
  `config:` が定義されているノードへ再投入します。
- プロジェクトが見つからない場合はエラーになります（先に `deploy` してください）。
- ノードが存在しない、または停止中の場合はそのノードだけスキップし、他のノードへの
  投入は続行します。

### 4. 状態確認

```
gns3lab list
```

サーバー上の全プロジェクトを name / status / project_id で一覧表示します。

### 5. 削除

```
gns3lab destroy mixed_lab
```

プロジェクト名（または project_id）を指定すると、全ノードを停止してからプロジェクトを削除します。

## GUI（サブコマンドをタブで選択）

コマンドを覚えなくても使えるGUI版があります。

```
gns3lab-gui
```

（`pip install -e .` 済みであれば上記コマンドで起動します）

タブ構成:

- **トポロジ編集**: 起動時に最初に開くタブ。左側でYAMLを直接編集でき、入力を止めて
  少し経つと右側の構成図（ノード種別ごとに色分けしたCanvas図）が自動的に再描画されます。
  YAMLが壊れていてもアプリはクラッシュせず、右下にエラー内容が表示されるだけです。
  「開く...」「保存」ボタンでファイルの読み込み・上書き保存ができます。
- **deploy**: トポロジファイルを指定して実行。「起動しない (--no-start)」「設定を投入
  しない (--no-config)」のチェックボックスと、「Deploy 実行」ボタンあり。
  隣の「設定を再投入 (configure)」ボタンは、既存プロジェクトを作り直さずに
  `config:` だけを再投入します（`gns3lab configure` と同じ）。
- **destroy**: プロジェクト名（またはproject_id）を指定して停止・削除。
- **list**: サーバー上の全プロジェクトを一覧表示。
- **templates**: 利用可能なテンプレート名を一覧表示。

実行結果は下部の出力欄にリアルタイム表示されます。

## exe化（Pythonなし環境向け）

Windows単体exeとしてビルドできます。配布先にPythonのインストールは不要です。

```
pip install pyinstaller

# CLI版
pyinstaller --onefile --name gns3lab --paths src scripts/build_entry.py

# GUI版
pyinstaller --onefile --windowed --name gns3lab-gui --paths src scripts/build_gui_entry.py
```

`dist/gns3lab.exe` / `dist/gns3lab-gui.exe` が生成されます。`gns3lab_config.yml` と `topology.yml` を同じフォルダに置いて実行してください。

```
gns3lab.exe templates
gns3lab.exe deploy topology.yml
gns3lab.exe list
gns3lab.exe destroy mixed_lab
```

GUI版はダブルクリックで起動し、タブでサブコマンドを選べます。
