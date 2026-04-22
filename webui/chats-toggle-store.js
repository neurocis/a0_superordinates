import { createStore } from "/js/AlpineStore.js";

export const store = createStore("chatsToggle", {
    hidden: false,

    init() {
        // Load state from localStorage
        const saved = localStorage.getItem("chatsToggle.hidden");
        if (saved !== null) {
            this.hidden = saved === "true";
        }
        
        // Apply initial state
        this.updateBodyClass();
    },

    toggle() {
        this.hidden = !this.hidden;
        localStorage.setItem("chatsToggle.hidden", this.hidden.toString());
        this.updateBodyClass();
    },

    updateBodyClass() {
        if (this.hidden) {
            document.body.classList.add("chats-hidden");
        } else {
            document.body.classList.remove("chats-hidden");
        }
    },
});
