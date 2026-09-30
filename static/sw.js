// 서비스 워커: 홈 화면 앱(PWA) 설치 + 푸시 알림 표시
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));

self.addEventListener('push', (e) => {
  let d = {};
  try { d = e.data.json(); } catch { d = { title: 'tmux 모니터', body: e.data?.text() || '' }; }
  e.waitUntil(self.registration.showNotification(d.title || 'tmux 모니터', {
    body: d.body || '',
    tag: d.tag,              // 같은 세션 알림은 하나로 교체
    renotify: true,
    icon: 'static/icons/icon-192.png',
    badge: 'static/icons/icon-192.png',
    data: { session: d.session },
  }));
});

// 알림을 누르면 해당 세션을 연 채로 앱을 띄움
self.addEventListener('notificationclick', (e) => {
  e.notification.close();
  const session = e.notification.data?.session;
  const url = new URL(session ? `./?s=${encodeURIComponent(session)}` : './', self.registration.scope).href;
  e.waitUntil((async () => {
    const wins = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    for (const w of wins) {
      if (w.url.startsWith(self.registration.scope)) {
        await w.focus();
        if (session) w.postMessage({ open: session });
        return;
      }
    }
    await self.clients.openWindow(url);
  })());
});
