"use strict";

// 图形验证码刷新与短信验证码发送（前台注册、找回密码与后台登录共用，不依赖 Bootstrap）
(() => {
  const refreshCaptcha = (img) => {
    if (img) img.src = `${img.src.split("?")[0]}?t=${Date.now()}`;
  };

  document.querySelectorAll("[data-captcha-refresh]").forEach((btn) => {
    btn.addEventListener("click", () => refreshCaptcha(btn.querySelector("img")));
  });
  document.querySelectorAll("img[data-captcha-refresh-self]").forEach((img) => {
    img.addEventListener("click", () => refreshCaptcha(img));
  });

  document.querySelectorAll("[data-sms-block]").forEach((block) => {
    const form = block.closest("form");
    const sendBtn = block.querySelector("[data-sms-send]");
    const status = block.querySelector("[data-sms-status]");
    const phone = form.querySelector(block.dataset.phoneInput);
    const captchaInput = block.querySelector("[data-captcha-input]");
    const captchaImg = block.querySelector("[data-captcha-img]");
    const codeInput = form.querySelector("[name=sms_code]");

    const say = (text, ok = false) => {
      status.textContent = text;
      status.className = `small mt-1 ${ok ? "text-success" : "text-danger"}`;
    };

    const countdown = (seconds) => {
      sendBtn.disabled = true;
      const tick = () => {
        if (seconds <= 0) {
          sendBtn.disabled = false;
          sendBtn.textContent = "重新获取";
          return;
        }
        sendBtn.textContent = `${seconds} 秒后重发`;
        seconds -= 1;
        setTimeout(tick, 1000);
      };
      tick();
    };

    sendBtn.addEventListener("click", async () => {
      if (!/^1\d{10}$/.test(phone.value.trim())) {
        say("请先填写正确的 11 位手机号");
        phone.focus();
        return;
      }
      if (captchaInput.value.trim().length !== 4) {
        say("请先填写图形验证码（看不清可点击图片更换）");
        captchaInput.focus();
        return;
      }
      sendBtn.disabled = true;
      try {
        const resp = await fetch(block.dataset.smsUrl, {
          method: "POST",
          headers: { "X-CSRFToken": form.querySelector("[name=csrfmiddlewaretoken]").value },
          body: new URLSearchParams({
            phone: phone.value.trim(),
            purpose: block.dataset.purpose,
            captcha: captchaInput.value.trim(),
          }),
        });
        const data = await resp.json();
        if (data.ok) {
          say(data.debug_code ? `${data.message}（开发环境验证码：${data.debug_code}）` : data.message, true);
          countdown(data.cooldown || 60);
          codeInput.focus();
        } else {
          say(data.message || "发送失败，请稍后再试");
          sendBtn.disabled = false;
        }
      } catch {
        say("网络异常，请检查网络后重试");
        sendBtn.disabled = false;
      } finally {
        captchaInput.value = "";
        refreshCaptcha(captchaImg);
      }
    });
  });
})();
