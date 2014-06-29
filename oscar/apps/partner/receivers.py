from django.db.models.signals import post_save

from oscar.core.loading import get_model

StockAlert = get_model('partner', 'StockAlert')
StockRecord = get_model('partner', 'StockRecord')


def update_stock_alerts(sender, instance, created, **kwargs):
    """
    Update low-stock alerts
    """
    if created or kwargs.get('raw', False):
        return
    stockrecord = instance
    try:
        alert = StockAlert.objects.get(stockrecord=stockrecord,
                                       status=StockAlert.OPEN)
    except StockAlert.DoesNotExist:
        alert = None

    if stockrecord.is_below_threshold and not alert:
        StockAlert.objects.create(stockrecord=stockrecord,
                                  threshold=stockrecord.low_stock_threshold)
    elif not stockrecord.is_below_threshold and alert:
        alert.close()


def register():
    post_save.connect(update_stock_alerts, sender=StockRecord)
