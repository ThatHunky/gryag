# GRYAG Bot Tools Implementation Plan

## Overview
This document outlines the implementation strategy for additional tools: Weather and Currency conversion. Calculator tool will be implemented first as it requires no external dependencies.

## 1. Weather Tool Implementation

### API Selection: OpenWeatherMap
- **Free Tier**: 1,000 calls/day
- **Rate Limit**: ~1 call per 86 seconds sustained
- **Documentation**: https://openweathermap.org/api
- **Pricing**: $0 for typical bot usage

### Environment Configuration
```bash
# Add to .env
OPENWEATHER_API_KEY=your_api_key_here
OPENWEATHER_BASE_URL=https://api.openweathermap.org/data/2.5
```

### Implementation Structure
```python
# app/services/weather.py
class WeatherService:
    def __init__(self, api_key: str, base_url: str):
        self.api_key = api_key
        self.base_url = base_url
        self.session = aiohttp.ClientSession()
    
    async def get_weather(self, location: str) -> dict[str, Any]:
        """Get current weather for location"""
        
    async def get_forecast(self, location: str, days: int = 3) -> dict[str, Any]:
        """Get weather forecast"""
```

### Tool Definition
```python
{
    "name": "weather",
    "description": "Отримати поточну погоду або прогноз для міста",
    "parameters": {
        "type": "object",
        "properties": {
            "location": {
                "type": "string",
                "description": "Назва міста або населеного пункту"
            },
            "forecast_days": {
                "type": "integer",
                "description": "Кількість днів прогнозу (1-5), за замовчуванням поточна погода",
                "minimum": 1,
                "maximum": 5
            }
        },
        "required": ["location"]
    }
}
```

### Response Format
```json
{
    "location": "Kyiv, UA",
    "temperature": 15,
    "feels_like": 13,
    "description": "Clear sky",
    "humidity": 65,
    "wind_speed": 3.5,
    "forecast": [...] // if requested
}
```

### Error Handling
- Invalid location → "Не вдалося знайти місто"
- API limit exceeded → "Перевищено ліміт запитів погоди"
- Network error → "Помилка отримання даних погоди"

## 2. Currency Converter Tool Implementation

### API Selection: ExchangeRate-API
- **Free Tier**: 1,500 calls/month
- **Rate Limit**: ~50 calls/day sustained
- **Documentation**: https://exchangerate-api.com/docs
- **Pricing**: $0 for typical bot usage

### Environment Configuration
```bash
# Add to .env
EXCHANGE_RATE_API_KEY=your_api_key_here
EXCHANGE_RATE_BASE_URL=https://v6.exchangerate-api.com/v6
```

### Implementation Structure
```python
# app/services/currency.py
class CurrencyService:
    def __init__(self, api_key: str, base_url: str):
        self.api_key = api_key
        self.base_url = base_url
        self.session = aiohttp.ClientSession()
        self._cache = {}  # Cache rates for 1 hour
    
    async def convert_currency(
        self, amount: float, from_currency: str, to_currency: str
    ) -> dict[str, Any]:
        """Convert currency with caching"""
        
    async def get_supported_currencies(self) -> list[str]:
        """Get list of supported currency codes"""
```

### Tool Definition
```python
{
    "name": "currency",
    "description": "Конвертувати валюту за поточним курсом",
    "parameters": {
        "type": "object",
        "properties": {
            "amount": {
                "type": "number",
                "description": "Сума для конвертації"
            },
            "from": {
                "type": "string",
                "description": "Валюта джерела (USD, EUR, UAH, etc.)"
            },
            "to": {
                "type": "string", 
                "description": "Цільова валюта (USD, EUR, UAH, etc.)"
            }
        },
        "required": ["amount", "from", "to"]
    }
}
```

### Response Format
```json
{
    "amount": 100,
    "from": "USD",
    "to": "UAH", 
    "rate": 41.25,
    "result": 4125.00,
    "last_updated": "2025-10-01T12:00:00Z"
}
```

### Caching Strategy
- Cache exchange rates for 1 hour
- Use Redis if available, fallback to in-memory
- Cache key format: `currency:rates:{base_currency}:{timestamp_hour}`

### Error Handling
- Invalid currency code → "Невідома валюта"
- API limit exceeded → "Перевищено ліміт запитів валют"
- Invalid amount → "Невірна сума"
- Network error → "Помилка отримання курсу валют"

## 3. Integration Timeline

### Phase 1: Calculator (Immediate)
- [x] No external dependencies
- [x] Safe math evaluation
- [x] Immediate implementation

### Phase 2: Weather (Week 1)
1. Sign up for OpenWeatherMap API
2. Create `app/services/weather.py`
3. Add environment variables
4. Implement tool and register in chat handler
5. Test with various locations

### Phase 3: Currency (Week 1-2)  
1. Sign up for ExchangeRate-API
2. Create `app/services/currency.py`
3. Implement caching mechanism
4. Add environment variables
5. Implement tool and register in chat handler
6. Test with popular currency pairs

## 4. Configuration Updates

### .env.example additions
```bash
# Weather API (optional)
OPENWEATHER_API_KEY=
OPENWEATHER_BASE_URL=https://api.openweathermap.org/data/2.5

# Currency API (optional)  
EXCHANGE_RATE_API_KEY=
EXCHANGE_RATE_BASE_URL=https://v6.exchangerate-api.com/v6
```

### app/config.py additions
```python
@dataclass
class Settings:
    # ... existing fields ...
    openweather_api_key: str = ""
    openweather_base_url: str = "https://api.openweathermap.org/data/2.5"
    exchange_rate_api_key: str = ""
    exchange_rate_base_url: str = "https://v6.exchangerate-api.com/v6"
```

## 5. Dependencies

### Additional requirements
```txt
aiohttp>=3.8.0  # Already in requirements.txt
```

### No additional dependencies needed - using existing aiohttp for HTTP calls

## 6. Testing Strategy

### Weather Tool Tests
- Valid city names (Kyiv, London, New York)
- Invalid city names
- Forecast requests
- API error simulation

### Currency Tool Tests  
- Common currency pairs (USD/UAH, EUR/USD)
- Invalid currency codes
- Edge cases (0 amount, negative amounts)
- Cache behavior testing

## 7. Persona Integration

Update `app/persona.py` to include tool descriptions:
```python
## Tools
- `search_messages`: Use when someone asks about stuff that might be present in past conversations.
- `calculator`: Use for mathematical calculations and expressions.
- `weather`: Use when someone asks about weather or forecast for any location.
- `currency`: Use when someone asks about currency conversion or exchange rates.
```

## 8. Monitoring & Limits

### API Usage Tracking
- Add telemetry counters for tool usage
- Monitor API limits approach
- Alert when approaching free tier limits

### Graceful Degradation
- Weather unavailable → "Сервіс погоди тимчасово недоступний"
- Currency unavailable → "Сервіс валют тимчасово недоступний"
- Calculator always works (no external dependencies)

## Next Steps
1. ✅ Implement calculator tool first
2. 🔄 Register for API keys
3. 🔄 Implement weather service
4. 🔄 Implement currency service
5. 🔄 Update documentation and examples