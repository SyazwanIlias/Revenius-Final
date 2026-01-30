/* static/main.js */

// Login Validation as per SDD [cite: 438]
document.addEventListener("DOMContentLoaded", function() {
    
    const loginForm = document.getElementById('loginForm');
    if (loginForm) {
        loginForm.addEventListener('submit', function(e) {
            const user = document.getElementById('username').value;
            const pass = document.getElementById('password').value;

            if (!user || !pass) {
                e.preventDefault();
                alert("Please fill up this field"); // [cite: 438]
            }
        });
    }
});

// Save Function
function saveContent(type) {
    const btn = document.querySelector('button.btn');
    const originalText = btn.innerText;
    
    // 1. Identify the content box
    let contentElement;
    if (type === 'summary') {
        contentElement = document.querySelector('.result-box');
    } else {
        contentElement = document.getElementById('quiz-container');
    }

    if (!contentElement) {
        alert("Error: Content to save not found.");
        return;
    }

    btn.innerText = "Saving & Downloading...";
    btn.disabled = true;

    // 2. SAVE ORIGINAL STYLES (So we can restore them later)
    const originalBg = contentElement.style.backgroundColor;
    const originalColor = contentElement.style.color;
    const originalBorder = contentElement.style.border;

    // 3. APPLY "PRINTER MODE" STYLES (White background, Black text)
    contentElement.style.backgroundColor = "white";
    contentElement.style.color = "black";
    contentElement.style.border = "none"; // Remove border for clean look
    
    // Force all text inside to be black
    const allText = contentElement.querySelectorAll('*');
    allText.forEach(el => {
        el.dataset.originalColor = el.style.color; // Remember old color
        el.style.color = 'black';
    });

    // 4. Save to Database
    fetch('/save_content', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ type: type }),
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            let safeName = data.new_filename.replace(/\s+/g, '_') + '.pdf';

            const opt = {
                margin:       0.5,
                filename:     safeName,
                image:        { type: 'jpeg', quality: 0.98 },
                html2canvas:  { scale: 2, useCORS: true }, // Added useCORS for better rendering
                jsPDF:        { unit: 'in', format: 'letter', orientation: 'portrait' }
            };

            // 5. Generate PDF from the NOW VISIBLE white element
            html2pdf().set(opt).from(contentElement).save().then(function() {
                // 6. RESTORE ORIGINAL STYLES (Go back to Dark Mode)
                contentElement.style.backgroundColor = originalBg;
                contentElement.style.color = originalColor;
                contentElement.style.border = originalBorder;
                
                allText.forEach(el => {
                    el.style.color = el.dataset.originalColor || ''; // Restore text colors
                });

                alert("Saved and Downloaded: " + safeName);
                window.location.href = '/mylibrary';
            });
            
        } else {
            // Restore styles if error
            contentElement.style.backgroundColor = originalBg;
            contentElement.style.color = originalColor;
            allText.forEach(el => el.style.color = el.dataset.originalColor || '');
            
            alert("Error saving: " + data.message);
            btn.innerText = originalText;
            btn.disabled = false;
        }
    })
    .catch((error) => {
        // Restore styles if crash
        contentElement.style.backgroundColor = originalBg;
        contentElement.style.color = originalColor;
        allText.forEach(el => el.style.color = el.dataset.originalColor || '');

        console.error('Error:', error);
        alert("An unexpected error occurred.");
        btn.innerText = originalText;
        btn.disabled = false;
    });
}