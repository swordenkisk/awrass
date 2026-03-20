# إعداد n8n مع أوراس | n8n Setup with Awrass

## طريقة 1: OpenAI Node (موصى بها)

1. في n8n، أنشئ بيانات اعتماد OpenAI جديدة
2. **Base URL**: `http://0.0.0.0:7777/v1`
3. **API Key**: `awrass-secret-2026`
4. استخدم هذه البيانات في أي AI Agent أو LLM Node

## طريقة 2: HTTP Request Node

```json
{
  "method": "POST",
  "url": "http://0.0.0.0:7777/v1/chat/completions",
  "headers": {
    "Authorization": "Bearer awrass-secret-2026",
    "Content-Type": "application/json"
  },
  "body": {
    "model": "gpt-4o-mini",
    "messages": [{"role": "user", "content": "{{ $json.input }}"}]
  }
}
```

## أداة Tool Calling في n8n Agent

أوراس يدعم Tool Calling بالكامل لـ n8n AI Agent nodes.
عيّن نفس بيانات الاعتماد وستعمل الأدوات تلقائياً.
