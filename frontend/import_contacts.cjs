// Node.js script to import contacts from CSV to CRM in dossier style
// Place this file in the frontend directory and run with: node import_contacts.js

const fs = require('fs');
const path = require('path');
const csv = require('csv-parser');
const axios = require('axios');

const CSV_PATH = path.join(__dirname, 'contacts.csv');
const API_URL = 'http://localhost:3000/cali/contacts'; // Adjust if backend runs elsewhere
const OWNER_EMAIL = 'bryan@spruked.com'; // Change as needed
const PLACEHOLDER_PHOTO = 'https://ui-avatars.com/api/?name=Contact&background=random';

function mapRowToContact(row) {
  // Merge all possible fields, add photo, and structure for dossier
  return {
    name: [row['First Name'], row['Middle Name'], row['Last Name']].filter(Boolean).join(' ').trim() || row['Company'] || row['Nickname'] || 'Unknown',
    email: row['E-mail Address'] || row['E-mail 2 Address'] || row['E-mail 3 Address'] || null,
    phone: row['Mobile Phone'] || row['Home Phone'] || row['Business Phone'] || row['Other Phone'] || null,
    address: [row['Home Street'], row['Home City'], row['Home State'], row['Home Postal Code'], row['Home Country/Region']].filter(Boolean).join(', ') || null,
    notes: row['Notes'] || null,
    contact_type: row['Company'] || row['Job Title'] || row['Department'] ? 'business' : 'personal',
    company: row['Company'] || null,
    job_title: row['Job Title'] || null,
    department: row['Department'] || null,
    photo: PLACEHOLDER_PHOTO,
    birthday: row['Birthday'] || null,
    anniversary: row['Anniversary'] || null,
    website: row['Web Page'] || row['Personal Web Page'] || null,
    owner: OWNER_EMAIL,
    // Add more fields as needed
    dossier: {
      links: [], // For future: add external links, social, etc.
      identity: {
        // For future: verification, status, etc.
      }
    }
  };
}

async function importContacts() {
  const contacts = [];
  fs.createReadStream(CSV_PATH)
    .pipe(csv())
    .on('data', (row) => {
      const contact = mapRowToContact(row);
      contacts.push(contact);
    })
    .on('end', async () => {
      console.log(`Parsed ${contacts.length} contacts. Importing...`);
      for (const contact of contacts) {
        try {
          await axios.post(API_URL, contact);
          console.log(`Imported: ${contact.name}`);
        } catch (err) {
          console.error(`Failed to import ${contact.name}:`, err.response?.data || err.message);
        }
      }
      console.log('Import complete.');
    });
}

importContacts();
