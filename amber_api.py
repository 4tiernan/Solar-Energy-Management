import requests
import time
from datetime import datetime, timedelta
from dataclasses import dataclass

@dataclass
class PriceForecast:
    price: float
    start_time: datetime
    end_time: datetime

@dataclass
class amber_data:
    general_price: float
    feedIn_price: float
    general_max_forecast_price: float
    feedIn_max_forecast_price: float
    general_12hr_forecast: list[PriceForecast]
    feedIn_12hr_forecast: list[PriceForecast]
    general_12hr_forecast_sorted: list[PriceForecast]
    feedIn_12hr_forecast_sorted: list[PriceForecast]
    


UTC_OFFSET = timedelta(hours=10) #UTC time, +10 for Brisbane

# 1) Get your site list
#sites = amber.get_sites()
#print("Your sites:", sites)

kwh_of_discharge_available = 15
max_discharge_rate = 15
hrs_of_discharge_available = kwh_of_discharge_available/max_discharge_rate

class AmberAPI:
    def __init__(self, api_key, site_id, errors):
        self.api_key = api_key
        self.site_id = site_id
        self.base = "https://api.amber.com.au/v1"

        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json"
        }
        self.errors = errors
        self.rate_limit_remaining = None
    
    def send_request(self, url):
        r = requests.get(url, headers=self.headers)
        self.rate_limit_remaining = r.headers.get("RateLimit-Remaining")

        # Check for rate limiting
        if r.status_code == 429:
            limit_policy = r.headers.get("RateLimit-Policy")
            if limit_policy:
                max_requests = limit_policy.split(";")[0]
                requests_window = limit_policy.split(";")[1].split("=")[1]
                print(f"Exceeded Amber API request rate limit ({max_requests}) within {requests_window} second window.")
                print(f"Waiting {requests_window} seconds before retrying")
                time.sleep(int(requests_window))
            else:
                print(f"Exceeded Amber API request rate limit.")
                print(f"Waiting 300 seconds before retrying")
                time.sleep(300)
            return self.send_request(url)
        
        return r.json()


    def get_sites(self):
        """Return all sites linked to your Amber account."""
        url = f"{self.base}/sites"
        return self.send_request(url)
        

    def get_forecast(self, next_intervals, resolution):
        """Return 12 hours of prices from now for a given site."""
        if(resolution != 30 and resolution != 5):
            if(self.errors):
                raise("Resolution must be 5 or 30 minutes not: "+str(resolution))

        url = (f"{self.base}/sites/{self.site_id}/prices/current?next={next_intervals}&previous=0&resolution={resolution}")

        general_price_forecast = []
        feed_in_price_forecast = []
        date_format = "%Y-%m-%dT%H:%M:%SZ"

        response = self.send_request(url)
        if(len(response) >= 2):
            for i in response:
                start = datetime.strptime(i["startTime"], date_format) + UTC_OFFSET
                end   = datetime.strptime(i["endTime"], date_format) + UTC_OFFSET

                if i["channelType"] == "general":
                    price = i["perKwh"]   
                    interval = PriceForecast(price=price, start_time=start, end_time=end)
                    general_price_forecast.append(interval)

                elif i["channelType"] == "feedIn":
                    price = -i["perKwh"]   
                    interval = PriceForecast(price=price, start_time=start, end_time=end)
                    feed_in_price_forecast.append(interval)

        return [general_price_forecast, feed_in_price_forecast]
    
    def get_current_prices(self):
        url = (f"{self.base}/sites/{self.site_id}/prices/current")

        response = self.send_request(url)
        if(len(response) >= 2):
            for i in response:
                if(i["channelType"] == "general"):
                    general_price = i["perKwh"]
                elif(i["channelType"] == "feedIn"):
                    feed_in_price = -i["perKwh"]

        return [general_price, feed_in_price]
    
    def get_data(self):
        [general_price, feed_in_price] = self.get_current_prices()
        [general_price_forecast, feed_in_price_forecast] = self.get_forecast(next_intervals=24, resolution=30)

        storted_general_forecast = feed_in_price_forecast.copy()
        storted_general_forecast.sort(key=lambda x: x.price, reverse=True)

        storted_feed_in_forecast = feed_in_price_forecast.copy()
        storted_feed_in_forecast.sort(key=lambda x: x.price, reverse=True)

        data = amber_data(
            general_price=round(general_price),
            feedIn_price=round(feed_in_price),
            general_max_forecast_price=round(storted_general_forecast[0].price),
            feedIn_max_forecast_price=round(storted_feed_in_forecast[0].price),
            general_12hr_forecast=general_price_forecast,
            feedIn_12hr_forecast=feed_in_price_forecast,
            general_12hr_forecast_sorted=storted_general_forecast,
            feedIn_12hr_forecast_sorted=storted_feed_in_forecast
            )
        return data

        
'''
amber = AmberAPI(AMBER_API_TOKEN, SITE_ID, errors=True)

[general_price, feed_in_price] = amber.get_current_prices()


#Get 12 hour forecast
[general_price_forecast, feed_in_price_forecast] = amber.get_forecast(next_intervals=24, resolution=30)

storted_feed_in_forecast = feed_in_price_forecast.copy()
storted_feed_in_forecast.sort(key=lambda x: x.price, reverse=True)

target_dispatch_price = storted_feed_in_forecast[max(round(hrs_of_discharge_available*2 - 1),0)].price

#print(storted_feed_in_forecast)


print(f"Current General Price: {round(general_price)} c/kWh")
print(f"Current FeedIn Price: {round(feed_in_price)} c/kWh")
print(f"Max Forecasted FeedIn Price: {round(storted_feed_in_forecast[0].price)} c/kWh")
print(f"Target Dispatch Price: {round(target_dispatch_price)} c/kWh")

'''
