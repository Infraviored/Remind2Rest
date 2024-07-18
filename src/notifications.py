from plyer import notification
import platform

def send_notification(title, message):
    if platform.system() == "Windows":
        from win10toast import ToastNotifier
        toaster = ToastNotifier()
        toaster.show_toast(title, message, duration=5)
    else:
        notification.notify(
            title=title,
            message=message,
            app_name="ReminderApp",
        )