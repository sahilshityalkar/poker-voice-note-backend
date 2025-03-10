from celery import Celery

app = Celery('cel_main', broker='pyamqp://dolmoyuh:rp1AyfkAQbbDrrgFVQ2Sqkfr_wRJBNZW@puffin.rmq2.cloudamqp.com/dolmoyuh')

