"use strict";

(() => {
  if (window.TalkBuddyMicManager) return;

  const micManager = {
    stream: null,
    streamPromise: null,

    async prime() {
      if (this.stream) return this.stream;
      if (this.streamPromise) return this.streamPromise;
      if (!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia)) return null;
      this.streamPromise = navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: false,
        },
        video: false,
      }).then((stream) => {
        this.stream = stream;
        return stream;
      }).catch(() => null);
      return this.streamPromise;
    },

    async acquire() {
      return this.stream || this.prime();
    },

    release() {
      if (this.stream) {
        this.stream.getTracks().forEach((track) => track.stop());
      }
      this.stream = null;
      this.streamPromise = null;
    },
  };

  window.TalkBuddyMicManager = micManager;
})();
