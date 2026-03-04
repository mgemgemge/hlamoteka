import statistics

def calculate_prices(device_name, raw_prices):
    """
    Анализирует сырые цены с досок объявлений и выдает 3 наших тарифа.
    """
    print(f"📊 Анализирую цены для: {device_name}")
    print(f"Сырые данные: {raw_prices}")

    # 1. Жесткий фильтр: отбрасываем явный мусор
    filtered_prices = [p for p in raw_prices if 1000 < p < 300000]
    
    if len(filtered_prices) < 3:
        return "Недостаточно данных для точной оценки рынка."

    # 2. Мягкий фильтр: убираем 15% с краев (только если данных достаточно)
    filtered_prices.sort()
    cut_index = int(len(filtered_prices) * 0.15)
    
    if cut_index > 0:
        core_prices = filtered_prices[cut_index : -cut_index]
    else:
        # Если цен мало (например, всего 6 штук), берем их все без среза
        core_prices = filtered_prices

    # 3. Высчитываем медиану (самую справедливую рыночную цену)
    market_price = int(statistics.median(core_prices))

    # 4. Формируем нашу вилку (наша бизнес-модель)
    quick_sell_price = int(market_price * 0.85) # -15% для быстрой продажи
    instant_buy_price = int(market_price * 0.70) # -30% выкуп нашими партнерами

    return {
        "market": market_price,
        "quick": quick_sell_price,
        "instant": instant_buy_price
    }

# --- ТЕСТОВЫЙ БЛОК ---
if __name__ == "__main__":
    mock_scraped_prices = [1, 500, 12000, 12500, 13000, 12800, 13500, 11000, 999999]
    result = calculate_prices("iPhone 11", mock_scraped_prices)
    
    # Добавил проверку, чтобы красиво выводить результат
    if isinstance(result, dict):
        print("\n💰 Вердикт ValueIt:")
        print(f"Рыночная цена: {result['market']} руб.")
        print(f"Быстрая продажа: {result['quick']} руб.")
        print(f"Мгновенный выкуп: {result['instant']} руб.")
    else:
        print(result)