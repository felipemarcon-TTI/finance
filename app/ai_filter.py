import json
from app.config import ANTHROPIC_API_KEY, USE_AI_FILTER

_client = None
_SYSTEM = ("You are a quantitative crypto trading signal validator. "
           "Analyze the signal and respond ONLY with valid JSON: "
           '{"approve": true/false, "confidence": 0-100, "reasoning": "max 15 words"}. '
           "Be conservative: reject signals with conflicting indicators or low-volume noise.")

def _get_client():
    global _client
    if _client is None:
        import anthropic
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client

def validate(signal, sentiment=None):
    if not USE_AI_FILTER or not ANTHROPIC_API_KEY:
        return True, 80, "AI disabled"
    try:
        funding = signal.get("funding")
        prompt = (
            f"Signal: {signal['symbol']} {signal['action']} {signal['timeframe']}\n"
            f"Price: {signal['price']:.4f} | RSI: {signal['rsi']:.1f}\n"
            f"EMA20: {signal['ema20']:.4f} > EMA50: {signal['ema50']:.4f}\n"
            f"ATR: {signal.get('atr',0):.4f} | Volume: {signal.get('vol_ratio',0):.2f}x avg\n"
            f"4h trend: {signal.get('trend_4h','N/A')} | "
            f"Funding: {funding:.5f if funding is not None else 'N/A'} | "
            f"Sentiment: {sentiment or 'N/A'}\n"
            "Approve?"
        )
        resp = _get_client().messages.create(
            model="claude-sonnet-4-6",
            max_tokens=80,
            system=[{"type":"text","text":_SYSTEM,"cache_control":{"type":"ephemeral"}}],
            messages=[{"role":"user","content":prompt}]
        )
        data = json.loads(resp.content[0].text)
        return bool(data.get("approve",True)), int(data.get("confidence",50)), str(data.get("reasoning",""))
    except Exception as e:
        print(f"[ai_filter] error: {e}")
        return True, 50, "AI error - fallback approved"
