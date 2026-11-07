// Keep a standard Dock item and Quit menu while the Python supervisor runs.
#import <Cocoa/Cocoa.h>

@interface CAMLauncher : NSObject <NSApplicationDelegate>
@property(nonatomic, strong) NSTask *task;
@property(nonatomic) BOOL quitting;
@end

@implementation CAMLauncher
- (void)applicationDidFinishLaunching:(NSNotification *)notification {
    NSURL *resources = NSBundle.mainBundle.resourceURL;
    NSURL *python = [NSBundle.mainBundle.executableURL.URLByDeletingLastPathComponent
                     URLByAppendingPathComponent:@"python3.14"];
    NSMutableDictionary *env = NSProcessInfo.processInfo.environment.mutableCopy;
    env[@"PYTHONHOME"] = [resources URLByAppendingPathComponent:@"python"].path;
    env[@"PYTHONNOUSERSITE"] = @"1";
    env[@"PYTHONDONTWRITEBYTECODE"] = @"1";
    [env removeObjectForKey:@"PYTHONPATH"];
    [env removeObjectForKey:@"PYTHONPYCACHEPREFIX"];

    self.task = [NSTask new];
    self.task.executableURL = python;
    self.task.currentDirectoryURL = [resources URLByAppendingPathComponent:@"CAM"];
    self.task.arguments = @[@"-B", [resources URLByAppendingPathComponent:@"start_cam.py"].path];
    self.task.environment = env;
    __weak CAMLauncher *launcher = self;
    self.task.terminationHandler = ^(NSTask *task) {
        dispatch_async(dispatch_get_main_queue(), ^{
            if (launcher.quitting) {
                [NSApp replyToApplicationShouldTerminate:YES];
            } else if (task.terminationStatus != 0) {
                [launcher reportFailure:@"See cam.log in Library → Application Support → CAM."];
            } else {
                [NSApp terminate:nil];
            }
        });
    };
    NSError *error;
    if (![self.task launchAndReturnError:&error]) {
        [self reportFailure:error.localizedDescription];
    }
}

- (void)reportFailure:(NSString *)detail {
    NSAlert *alert = [NSAlert new];
    alert.messageText = @"CAM could not start or stopped unexpectedly.";
    alert.informativeText = detail;
    [NSApp activateIgnoringOtherApps:YES];
    [alert runModal];
    [NSApp terminate:nil];
}

- (BOOL)applicationShouldHandleReopen:(NSApplication *)app hasVisibleWindows:(BOOL)visible {
    if (self.task.running && !self.quitting) {
        kill(self.task.processIdentifier, SIGUSR1);
    }
    return YES;
}

- (NSApplicationTerminateReply)applicationShouldTerminate:(NSApplication *)app {
    if (!self.task.running) return NSTerminateNow;
    self.quitting = YES;
    [self.task terminate];
    return NSTerminateLater;
}
@end

int main(void) {
    signal(SIGUSR1, SIG_IGN);
    @autoreleasepool {
        NSApplication *app = NSApplication.sharedApplication;
        [app setActivationPolicy:NSApplicationActivationPolicyRegular];
        CAMLauncher *launcher = [CAMLauncher new];
        app.delegate = launcher;
        NSMenu *menuBar = [NSMenu new];
        NSMenuItem *appItem = [NSMenuItem new];
        [menuBar addItem:appItem];
        NSMenu *menu = [[NSMenu alloc] initWithTitle:@"CAM"];
        [menu addItemWithTitle:@"Quit CAM" action:@selector(terminate:) keyEquivalent:@"q"];
        appItem.submenu = menu;
        app.mainMenu = menuBar;
        [app run];
    }
    return 0;
}
