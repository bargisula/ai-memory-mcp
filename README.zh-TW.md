# ai-memory-mcp

給 AI 程式助理用的本機共用記憶，以 Markdown 為核心，透過 [MCP](https://modelcontextprotocol.io) 提供服務。

每個工具（Claude Code、Codex CLI、Copilot CLI……）每次開新 session 都是失憶的。這個工具給它們一個共用的地方，
記下決策、踩過的坑、交接摘要，下次直接查，不用再對每個 AI 重新解釋專案。

> **狀態：功能完整，照現狀提供。** 這是我自己在用的小工具，不提供支援、不接受功能請求，
> 問題回報可能不會回覆。歡迎自行 fork（MIT 授權）。

## 特色

- **Markdown 是唯一真相來源**：一則記憶一個 `.md` 檔，人看得懂、能 grep、能 diff、能進 git。
- **索引可以丟**：SQLite 只負責加速搜尋，刪掉 `index.db` 會從筆記自動重建。
- **全在本機**：沒有雲端、不用帳號。語意搜尋（選用）用本機 Ollama。
- **中文子字串搜尋可用**：不是只能搜用空格分開的詞。
- **可稽核**：每次讀取都記錄誰、何時、查什麼（不記錄結果內容）。

## 安裝

需要 Python 3.10+。

```bash
git clone <本專案>
cd ai-memory-mcp
pipx install .          # 或 pip install .
ai-memory doctor        # 檢查環境
```

註冊到 MCP client，指令是 `ai-memory-mcp`（stdio）：

```bash
claude mcp add -s user ai-memory -- ai-memory-mcp     # Claude Code
codex mcp add ai-memory -- ai-memory-mcp              # Codex CLI
```

用 JSON 設定的工具（例如 `~/.copilot/mcp-config.json`）：

```json
{ "mcpServers": { "ai-memory": { "command": "ai-memory-mcp" } } }
```

Server 會自動把使用說明送給 client（開工先看交接、做完決策就記錄），不需要另外寫提示檔。

## 工具

| 工具 | 用途 |
|---|---|
| `record_memory` | 寫一筆。`type` 為 `decision`／`progress`／`failure`／`handoff` |
| `search_memory` | 子字串搜尋，每個詞都要命中，回傳短摘要 |
| `search_memory_semantic` | 語意搜尋（需 Ollama） |
| `read_memory(path)` | 讀單則全文 |
| `get_handoff(project)` | 最新交接摘要（含全文），接續工作時先呼叫 |
| `recent`／`list_projects`／`audit_usage` | 最近紀錄／專案清單／讀取稽核 |

呼叫時請帶上自己的名字到 `llm` 欄位（例如 `"Claude"`）。

## 資料放哪

預設 `~/.ai-memory/`（用 `AI_MEMORY_HOME` 改）：

- `notes/<project>/*.md`：真相來源，請備份或放進 git
- `index.db`：可丟棄的搜尋索引與稽核紀錄

手動編輯、刪除筆記，或從別台電腦複製筆記過來之後，執行 `ai-memory reindex`。`index.db` 不存在時，server 第一次啟動會自動重建。

## 設定（皆為選用的環境變數）

`AI_MEMORY_HOME`、`AI_MEMORY_TYPES`（允許的類型，逗號分隔）、`AI_MEMORY_EMBEDDINGS`（`off` 關閉語意搜尋）、
`AI_MEMORY_EMBED_URL`、`AI_MEMORY_EMBED_MODEL`。預設值見英文版 README。

## 語意搜尋（選用）

```bash
ollama pull nomic-embed-text
ai-memory reindex --embed
```

沒有 Ollama 時其他功能都正常，語意搜尋只會回報「不可用」。向量用純 Python 暴力比對，幾千筆內都夠用。

## 讓交接自動載入（Claude Code）

靠模型自己記得呼叫 `get_handoff` 不可靠，用 `SessionStart` hook 才能保證。專案的 `.claude/settings.json`：

```json
{
  "hooks": {
    "SessionStart": [
      { "hooks": [ { "type": "command", "command": "ai-memory handoff my-app" } ] }
    ]
  }
}
```

## 安全

- 專案名只允許字母、數字、`_`、`-`、`.`，任何像路徑的輸入都會被拒絕；`read_memory` 也只能讀 `notes/` 底下的 `.md`。
- 筆記是明文檔案，**不要把密碼或金鑰寫進記憶**。

## 已知限制（刻意如此）

- 單人單機。並行寫入是安全的，但沒有權限控管、沒有內建同步（要同步就把 `notes/` 放進 git）。
- 沒有編輯／刪除工具：直接改或刪 Markdown 檔，再 `ai-memory reindex`。
- 搜尋是子字串比對，不是模糊搜尋（要找語意相近請用語意工具）。

## 從舊版私有系統搬過來

筆記格式沒有變：把舊的 `notes/` 資料夾複製到 `AI_MEMORY_HOME`，啟動即可，索引會自動建立。

## 授權

MIT，見 [LICENSE](LICENSE)。
